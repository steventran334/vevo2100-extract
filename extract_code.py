import streamlit as st
import cv2
import tempfile
import os
import zipfile
import io

# --- Page Configuration ---
st.set_page_config(page_title="Vevo 2100 Frame Editor", layout="centered")
st.title("Vevo 2100 Video Editor (Batch)")

st.markdown("""
**Instructions:**
1. **Upload** your videos.
2. **Select Video** to preview.
3. **Find Frame:** Use the scrubber and Prev/Next buttons to find the exact image.
4. **Lock It:** Click **"Set as Start"** or **"Set as End"** to lock that frame, ignoring any number drift.
5. **Process:** Generate your clips.
""")

# --- File Uploader ---
uploaded_files = st.file_uploader(
    "Upload video(s) (.mp4, .avi, .mov)", 
    type=["mp4", "avi", "mov"], 
    accept_multiple_files=True
)

def clamp(val, lo, hi):
    return max(lo, min(hi, val))

if uploaded_files:
    
    # --- 1. Video Selector ---
    file_map = {f.name: f for f in uploaded_files}
    selected_name = st.selectbox("Select Video to Preview/Setup", list(file_map.keys()))
    selected_file = file_map[selected_name]

    # --- 2. Read Metadata ---
    tfile = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(selected_file.name)[1])
    selected_file.seek(0)
    tfile.write(selected_file.read())
    tfile.flush()
    
    cap = cv2.VideoCapture(tfile.name)
    
    if not cap.isOpened():
        st.error("Error opening video file.")
        total_frames = 1
        detected_fps = 30.0
        W, H = 640, 480
    else:
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        detected_fps = cap.get(cv2.CAP_PROP_FPS)
        W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        if total_frames <= 0: total_frames = 100
        if detected_fps <= 0: detected_fps = 30.0

    st.sidebar.header("Processing Settings")

    # --- 3. FPS Input ---
    st.sidebar.subheader("1. Playback Speed")
    user_fps = st.sidebar.number_input(
        "Capture FPS", 
        min_value=1.0, 
        max_value=1000.0, 
        value=float(detected_fps), 
        step=1.0,
        help="Sets the playback speed of the saved video."
    )
    
    # --- Initialize State ---
    if 'current_video_name' not in st.session_state or st.session_state.current_video_name != selected_name:
        st.session_state.current_video_name = selected_name
        st.session_state.num_start = 0
        st.session_state.num_end = total_frames - 1
        st.session_state.preview_frame = 0

    # Ensure valid bounds
    if st.session_state.preview_frame >= total_frames:
        st.session_state.preview_frame = total_frames - 1

    # --- 4. Interactive Preview & Navigation ---
    st.subheader(f"Preview: {selected_name}")

    # Slider for rough seeking
    # We use a callback here so the slider can update the preview state
    def update_preview_from_slider():
        st.session_state.preview_frame = st.session_state.preview_slider

    slider_val = st.slider(
        "Scrub Timeline", 
        min_value=0, 
        max_value=total_frames - 1, 
        value=st.session_state.preview_frame,
        step=1,
        key="preview_slider",
        on_change=update_preview_from_slider
    )

    # Fine-Tuning Buttons (Prev / Next)
    c_prev, c_mid, c_next = st.columns([1, 3, 1])
    with c_prev:
        if st.button("⏪ Prev Frame"):
            st.session_state.preview_frame = max(0, st.session_state.preview_frame - 1)
            st.rerun()
    
    with c_next:
        if st.button("Next Frame ⏩"):
            st.session_state.preview_frame = min(total_frames - 1, st.session_state.preview_frame + 1)
            st.rerun()

    # --- Display Image ---
    current_frame_idx = st.session_state.preview_frame
    cap.set(cv2.CAP_PROP_POS_FRAMES, current_frame_idx)
    ret, frame_preview = cap.read()
    
    # --- Spatial Crop Overlay ---
    # We define crop settings here so they can be drawn on the preview
    st.sidebar.subheader("3. Spatial Crop")
    default_x0, default_x1 = 0.00, 1.00
    default_y0, default_y1 = 0.21, 0.55
    c_side1, c_side2 = st.sidebar.columns(2)
    with c_side1:
        x0 = st.slider("Left (%)", 0.0, 1.0, default_x0, 0.01)
        x1 = st.slider("Right (%)", 0.0, 1.0, default_x1, 0.01)
    with c_side2:
        y0 = st.slider("Top (%)", 0.0, 1.0, default_y0, 0.01)
        y1 = st.slider("Bottom (%)", 0.0, 1.0, default_y1, 0.01)

    x_start = int(clamp(x0, 0, 1) * W)
    x_end   = int(clamp(x1, 0, 1) * W)
    y_start = int(clamp(y0, 0, 1) * H)
    y_end   = int(clamp(y1, 0, 1) * H)
    if x_end <= x_start: x_end = x_start + 1
    if y_end <= y_start: y_end = y_start + 1
    crop_w = x_end - x_start
    crop_h = y_end - y_start

    if ret:
        overlay = frame_preview.copy()
        cv2.rectangle(overlay, (x_start, y_start), (x_end, y_end), (0, 255, 0), 2)
        st.image(
            cv2.cvtColor(overlay, cv2.COLOR_BGR2RGB), 
            use_container_width=True, 
            caption=f"Currently Viewing Frame: {current_frame_idx}"
        )
    else:
        st.warning("Could not read frame.")

    st.markdown("---")

    # --- 5. "Lock" Buttons (The Solution to Drift) ---
    st.subheader("2. Set Cut Points from Preview")
    st.info("Use the Prev/Next buttons above to match the image to your notes, then click 'Set' below. This ignores the number mismatch.")

    col_set_start, col_set_end = st.columns(2)
    
    with col_set_start:
        if st.button("👇 Set Current Frame as START"):
            st.session_state.num_start = current_frame_idx
            # Auto-correct end if it's before start
            if st.session_state.num_end < st.session_state.num_start:
                st.session_state.num_end = total_frames - 1
            st.success(f"Start set to {current_frame_idx}")

    with col_set_end:
        if st.button("👇 Set Current Frame as END"):
            st.session_state.num_end = current_frame_idx
            # Auto-correct start if it's after end
            if st.session_state.num_start > st.session_state.num_end:
                st.session_state.num_start = 0
            st.success(f"End set to {current_frame_idx}")

    # Display Current Selection
    st.markdown(f"**Current Selection:** Frame **{st.session_state.num_start}** to **{st.session_state.num_end}**")
    st.caption(f"(Duration: {st.session_state.num_end - st.session_state.num_start + 1} frames)")

    cap.release()
    try: os.unlink(tfile.name)
    except: pass

    st.markdown("---")

    # --- 6. Batch Processing Logic ---
    if 'processed_zip' not in st.session_state:
        st.session_state['processed_zip'] = None

    if st.button(f"Process All {len(uploaded_files)} Video(s)"):
        progress_bar = st.progress(0.0)
        status_text = st.empty()
        zip_buffer = io.BytesIO()
        
        # We use the Start/End frames set in Session State
        final_start = st.session_state.num_start
        final_end = st.session_state.num_end
        
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
            for i, uploaded_file in enumerate(uploaded_files):
                status_text.text(f"Processing {uploaded_file.name}...")
                uploaded_file.seek(0)
                t_in = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[1])
                t_in.write(uploaded_file.read())
                t_in.flush()
                t_in.close()

                vcap = cv2.VideoCapture(t_in.name)
                base_name = os.path.splitext(uploaded_file.name)[0]
                out_name = f"{base_name}_frames_{final_start}-{final_end}.mp4"
                
                t_out = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
                t_out_name = t_out.name
                t_out.close()
                
                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                writer = cv2.VideoWriter(t_out_name, fourcc, user_fps, (crop_w, crop_h))
                
                current_frame = 0
                while True:
                    ok, frame = vcap.read()
                    if not ok: break
                    
                    if final_start <= current_frame <= final_end:
                        if frame.shape[0] >= y_end and frame.shape[1] >= x_end:
                            crop = frame[y_start:y_end, x_start:x_end]
                            if crop.shape[0] > 0 and crop.shape[1] > 0:
                                writer.write(crop)
                    
                    current_frame += 1
                    if current_frame > final_end: break
                
                vcap.release()
                writer.release()
                try: os.unlink(t_in.name)
                except: pass
                zipf.write(t_out_name, arcname=out_name)
                try: os.unlink(t_out_name)
                except: pass
                progress_bar.progress((i + 1) / len(uploaded_files))

        status_text.success("✅ Processing Complete!")
        zip_buffer.seek(0)
        st.session_state['processed_zip'] = zip_buffer.getvalue()

    if st.session_state['processed_zip'] is not None:
        st.download_button(
            label="⬇️ Download All Processed Videos (ZIP)",
            data=st.session_state['processed_zip'],
            file_name="vevo_processed_videos.zip",
            mime="application/zip"
        )

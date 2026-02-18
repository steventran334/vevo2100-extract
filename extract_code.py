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
2. **Select Video**: Choose which video to preview.
3. **Offset**: **Enter '6'** (or the difference you see) in the Frame Offset box to sync the numbers.
4. **Trim**: Set your start/end points.
5. **Process**: Generates the cropped/trimmed files.
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
        help="This affects the output playback speed and the 'Time' calculation."
    )
    
    # --- 4. Frame Offset (THE FIX) ---
    st.sidebar.subheader("2. Frame Correction")
    offset = st.sidebar.number_input(
        "Frame Offset (+/-)",
        value=0,
        step=1,
        help="Example: If App says 311 but Video says 317, enter 6 here. The app will sync the numbers."
    )

    # --- 5. Synchronized Frame Trimming ---
    st.sidebar.subheader("3. Trim Video")
    
    # Calculate bounds based on offset
    max_display_frame = (total_frames - 1) + offset
    min_display_frame = 0 + offset
    
    st.sidebar.caption(f"Raw Internal Frames: 0 to {total_frames-1}")

    # Initialize State
    if 'current_video_name' not in st.session_state or st.session_state.current_video_name != selected_name:
        st.session_state.current_video_name = selected_name
        st.session_state.num_start = 0 + offset
        st.session_state.num_end = (total_frames - 1) + offset
        st.session_state.slider_range = (0 + offset, (total_frames - 1) + offset)
        st.session_state.preview_frame = 0 + offset
        st.session_state.last_start = 0 + offset
        st.session_state.last_end = (total_frames - 1) + offset

    # Callbacks
    def update_slider_from_num():
        s = st.session_state.num_start
        e = st.session_state.num_end
        if s > e: s = e 
        st.session_state.slider_range = (s, e)
        if s != st.session_state.last_start:
            st.session_state.preview_frame = s
        elif e != st.session_state.last_end:
            st.session_state.preview_frame = e
        st.session_state.last_start = s
        st.session_state.last_end = e

    def update_num_from_slider():
        s, e = st.session_state.slider_range
        st.session_state.num_start = s
        st.session_state.num_end = e
        if s != st.session_state.last_start:
            st.session_state.preview_frame = s
        elif e != st.session_state.last_end:
            st.session_state.preview_frame = e
        st.session_state.last_start = s
        st.session_state.last_end = e

    # Inputs
    col_start, col_end = st.sidebar.columns(2)
    with col_start:
        st.number_input("Start Frame", value=st.session_state.num_start, key="num_start", on_change=update_slider_from_num)
    with col_end:
        st.number_input("End Frame", value=st.session_state.num_end, key="num_end", on_change=update_slider_from_num)

    start_display, end_display = st.sidebar.slider(
        "Frame Range",
        min_value=min_display_frame,
        max_value=max_display_frame,
        value=st.session_state.slider_range,
        key="slider_range",
        step=1,
        on_change=update_num_from_slider
    )
    
    # Calculate Actual Frames for processing (Subtract offset)
    actual_start = clamp(start_display - offset, 0, total_frames - 1)
    actual_end = clamp(end_display - offset, 0, total_frames - 1)
    
    st.sidebar.info(f"Duration: {actual_end - actual_start + 1} frames")

    # --- 6. Spatial Cropping ---
    st.sidebar.subheader("4. Spatial Crop")
    default_x0, default_x1 = 0.00, 1.00
    default_y0, default_y1 = 0.21, 0.55
    c1, c2 = st.sidebar.columns(2)
    with c1:
        x0 = st.slider("Left (%)", 0.0, 1.0, default_x0, 0.01)
        x1 = st.slider("Right (%)", 0.0, 1.0, default_x1, 0.01)
    with c2:
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

    # --- 7. Interactive Preview ---
    st.subheader(f"Preview: {selected_name}")
    
    if 'preview_frame' not in st.session_state:
        st.session_state.preview_frame = 0 + offset

    # Slider allows scrubbing full video, even outside trim
    preview_frame_display = st.slider(
        "Scrub Timeline", 
        min_value=min_display_frame, 
        max_value=max_display_frame, 
        value=st.session_state.preview_frame,
        step=1,
        key="preview_slider"
    )

    actual_preview_frame = clamp(preview_frame_display - offset, 0, total_frames - 1)

    cap.set(cv2.CAP_PROP_POS_FRAMES, actual_preview_frame)
    ret, frame_preview = cap.read()

    if ret:
        current_time = actual_preview_frame / user_fps
        overlay = frame_preview.copy()
        cv2.rectangle(overlay, (x_start, y_start), (x_end, y_end), (0, 255, 0), 2)
        
        # Display the offset-corrected frame number
        st.image(
            cv2.cvtColor(overlay, cv2.COLOR_BGR2RGB), 
            use_container_width=True, 
            caption=f"App Frame: {preview_frame_display} | Vevo Time: {current_time:.3f}s"
        )
        
        if st.button("▶️ Play 1s Clip (Motion Check)"):
            with st.spinner("Rendering preview clip..."):
                t_prev = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                preview_writer = cv2.VideoWriter(t_prev.name, fourcc, user_fps, (crop_w, crop_h))
                frames_to_render = int(user_fps) 
                cap.set(cv2.CAP_PROP_POS_FRAMES, actual_preview_frame)
                for _ in range(frames_to_render):
                    ret_p, frame_p = cap.read()
                    if not ret_p: break
                    crop_p = frame_p[y_start:y_end, x_start:x_end]
                    if crop_p.shape[0] > 0 and crop_p.shape[1] > 0:
                        preview_writer.write(crop_p)
                preview_writer.release()
                st.video(t_prev.name)

    else:
        st.warning("Could not read frame.")
    
    cap.release()
    try: os.unlink(tfile.name)
    except: pass

    st.markdown("---")

    # --- 8. Batch Processing Logic ---
    if 'processed_zip' not in st.session_state:
        st.session_state['processed_zip'] = None

    if st.button(f"Process All {len(uploaded_files)} Video(s)"):
        progress_bar = st.progress(0.0)
        status_text = st.empty()
        zip_buffer = io.BytesIO()
        
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
                out_name = f"{base_name}_frames_{actual_start}-{actual_end}.mp4"
                
                t_out = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
                t_out_name = t_out.name
                t_out.close()
                
                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                writer = cv2.VideoWriter(t_out_name, fourcc, user_fps, (crop_w, crop_h))
                
                current_frame = 0
                while True:
                    ok, frame = vcap.read()
                    if not ok: break
                    if actual_start <= current_frame <= actual_end:
                        if frame.shape[0] >= y_end and frame.shape[1] >= x_end:
                            crop = frame[y_start:y_end, x_start:x_end]
                            if crop.shape[0] > 0 and crop.shape[1] > 0:
                                writer.write(crop)
                    current_frame += 1
                    if current_frame > actual_end: break
                
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

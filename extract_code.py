import streamlit as st
import cv2
import tempfile
import os
import zipfile
import io
import imageio

# --- Page Configuration ---
st.set_page_config(page_title="Vevo 2100 Frame Editor", layout="centered")
st.title("Vevo 2100 Video Editor (Batch)")

st.markdown("""
**Instructions:**
1. **Upload** your videos (GIFs recommended for exact frame syncing).
2. **Select Video**: Choose which video to preview.
3. **Trim**: Set your start/end points.
4. **Split-Pane Crop**: Box out the B-mode and NLC panes. The app will stitch them together.
5. **Format**: Choose MP4 or GIF for your final downloaded files.
6. **Process**: Generates the cropped/trimmed files.
""")

# --- File Uploader ---
uploaded_files = st.file_uploader(
    "Upload video(s) (.gif, .mp4, .avi, .mov)", 
    type=["gif", "mp4", "avi", "mov"], 
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
    
    # --- 4. Synchronized Frame Trimming (1-Based Indexing) ---
    st.sidebar.subheader("2. Trim Video")
    
    # UI Display bounds starting at 1
    max_display_frame = total_frames
    min_display_frame = 1
    
    st.sidebar.caption(f"Total Frames: {total_frames}")

    # Initialize State with 1-based indexing
    if 'current_video_name' not in st.session_state or st.session_state.current_video_name != selected_name:
        st.session_state.current_video_name = selected_name
        st.session_state.num_start = 1
        st.session_state.num_end = total_frames
        st.session_state.slider_range = (1, total_frames)
        st.session_state.preview_frame = 1
        st.session_state.last_start = 1
        st.session_state.last_end = total_frames

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
    
    # Map back to 0-based index for OpenCV internal processing
    actual_start = clamp(start_display - 1, 0, total_frames - 1)
    actual_end = clamp(end_display - 1, 0, total_frames - 1)
    
    st.sidebar.info(f"Duration: {actual_end - actual_start + 1} frames")

    # --- 5. Split-Pane Spatial Cropping ---
    st.sidebar.subheader("3. Split-Pane Crop")
    
    st.sidebar.markdown("**Global Height**")
    c1, c2 = st.sidebar.columns(2)
    with c1: y0 = st.slider("Top (%)", 0.0, 1.0, 0.35, 0.01)
    with c2: y1 = st.slider("Bottom (%)", 0.0, 1.0, 0.48, 0.01)

    st.sidebar.markdown("**Left Image (B-Mode)**")
    c3, c4 = st.sidebar.columns(2)
    with c3: lx0 = st.slider("L-Start (%)", 0.0, 1.0, 0.08, 0.01)
    with c4: lx1 = st.slider("L-End (%)", 0.0, 1.0, 0.42, 0.01)

    st.sidebar.markdown("**Right Image (NLC)**")
    c5, c6 = st.sidebar.columns(2)
    with c5: rx0 = st.slider("R-Start (%)", 0.0, 1.0, 0.54, 0.01)
    with c6: rx1 = st.slider("R-End (%)", 0.0, 1.0, 0.88, 0.01)

    # Convert percentages to pixels
    y_start = int(clamp(y0, 0, 1) * H)
    y_end   = int(clamp(y1, 0, 1) * H)
    lx_start = int(clamp(lx0, 0, 1) * W)
    lx_end   = int(clamp(lx1, 0, 1) * W)
    rx_start = int(clamp(rx0, 0, 1) * W)
    rx_end   = int(clamp(rx1, 0, 1) * W)

    # Failsafes
    if y_end <= y_start: y_end = y_start + 1
    if lx_end <= lx_start: lx_end = lx_start + 1
    if rx_end <= rx_start: rx_end = rx_start + 1

    crop_h = y_end - y_start
    crop_w_left = lx_end - lx_start
    crop_w_right = rx_end - rx_start
    final_w = crop_w_left + crop_w_right

    # --- 6. Export Format Selection ---
    st.sidebar.subheader("4. Export Format")
    export_format = st.sidebar.radio("Choose output format:", ["MP4", "GIF"])

    # --- 7. Interactive Preview ---
    st.subheader(f"Preview: {selected_name}")
    
    if 'preview_frame' not in st.session_state:
        st.session_state.preview_frame = 1

    preview_frame_display = st.slider(
        "Scrub Timeline", 
        min_value=min_display_frame, 
        max_value=max_display_frame, 
        value=st.session_state.preview_frame,
        step=1,
        key="preview_slider"
    )

    # Convert the 1-based display value to 0-based for OpenCV
    actual_preview_frame = clamp(preview_frame_display - 1, 0, total_frames - 1)

    cap.set(cv2.CAP_PROP_POS_FRAMES, actual_preview_frame)
    ret, frame_preview = cap.read()

    if ret:
        current_time = actual_preview_frame / user_fps
        overlay = frame_preview.copy()
        
        # Draw the two crop boxes on the overlay
        cv2.rectangle(overlay, (lx_start, y_start), (lx_end, y_end), (0, 255, 0), 2)
        cv2.rectangle(overlay, (rx_start, y_start), (rx_end, y_end), (0, 255, 0), 2)
        
        st.image(
            cv2.cvtColor(overlay, cv2.COLOR_BGR2RGB), 
            use_container_width=True, 
            caption=f"Frame: {preview_frame_display} | Vevo Time: {current_time:.3f}s"
        )
        
        # Preview Controls
        col_btn1, col_btn2 = st.columns(2)
        
        with col_btn1:
            if st.button("▶️ Play 1s Clip"):
                with st.spinner("Rendering preview clip..."):
                    t_prev = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
                    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                    preview_writer = cv2.VideoWriter(t_prev.name, fourcc, user_fps, (final_w, crop_h))
                    frames_to_render = int(user_fps) 
                    cap.set(cv2.CAP_PROP_POS_FRAMES, actual_preview_frame)
                    
                    for _ in range(frames_to_render):
                        ret_p, frame_p = cap.read()
                        if not ret_p: break
                        
                        # Extract both panes and stitch them together
                        crop_left = frame_p[y_start:y_end, lx_start:lx_end]
                        crop_right = frame_p[y_start:y_end, rx_start:rx_end]
                        
                        if crop_left.shape[0] > 0 and crop_right.shape[0] > 0:
                            stitched_frame = cv2.hconcat([crop_left, crop_right])
                            preview_writer.write(stitched_frame)
                            
                    preview_writer.release()
                    st.video(t_prev.name)
                    
        with col_btn2:
            # Slice from the original clean frame, not the overlay
            crop_left_clean = frame_preview[y_start:y_end, lx_start:lx_end]
            crop_right_clean = frame_preview[y_start:y_end, rx_start:rx_end]
            
            if crop_left_clean.shape[0] > 0 and crop_right_clean.shape[0] > 0:
                stitched_clean = cv2.hconcat([crop_left_clean, crop_right_clean])
                is_success, buffer = cv2.imencode(".png", stitched_clean)
                
                if is_success:
                    base_name = os.path.splitext(selected_name)[0]
                    dl_name = f"{base_name}_frame_{preview_frame_display}.png"
                    
                    st.download_button(
                        label="📸 Download Current Frame",
                        data=buffer.tobytes(),
                        file_name=dl_name,
                        mime="image/png"
                    )

    else:
        st.warning("Could not read frame.")
    
    cap.release()
    try: os.unlink(tfile.name)
    except: pass

    st.markdown("---")

    # --- 8. Batch Processing Logic ---
    if 'processed_zip' not in st.session_state:
        st.session_state['processed_zip'] = None

    if st.button(f"Process All {len(uploaded_files)} Video(s) as {export_format}"):
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
                
                # Output filename dynamically sets the extension
                ext = ".mp4" if export_format == "MP4" else ".gif"
                out_name = f"{base_name}_frames_{start_display}-{end_display}{ext}"
                
                t_out = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
                t_out_name = t_out.name
                t_out.close()
                
                # Initialize correct writer based on format
                if export_format == "MP4":
                    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                    writer = cv2.VideoWriter(t_out_name, fourcc, user_fps, (final_w, crop_h))
                else:
                    # imageio writer for GIFs
                    writer = imageio.get_writer(t_out_name, mode='I', fps=user_fps)
                
                current_frame = 0
                while True:
                    ok, frame = vcap.read()
                    if not ok: break
                    if actual_start <= current_frame <= actual_end:
                        # Ensure frame bounds are valid before slicing
                        if frame.shape[0] >= y_end and frame.shape[1] >= max(lx_end, rx_end):
                            crop_left = frame[y_start:y_end, lx_start:lx_end]
                            crop_right = frame[y_start:y_end, rx_start:rx_end]
                            
                            if crop_left.shape[0] > 0 and crop_right.shape[0] > 0:
                                stitched_frame = cv2.hconcat([crop_left, crop_right])
                                
                                if export_format == "MP4":
                                    writer.write(stitched_frame)
                                else:
                                    # imageio requires RGB format, OpenCV uses BGR natively
                                    rgb_frame = cv2.cvtColor(stitched_frame, cv2.COLOR_BGR2RGB)
                                    writer.append_data(rgb_frame)
                                
                    current_frame += 1
                    if current_frame > actual_end: break
                
                vcap.release()
                
                # Release correct writer
                if export_format == "MP4":
                    writer.release()
                else:
                    writer.close()
                    
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

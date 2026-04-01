import streamlit as st
import cv2
import tempfile
import os
import zipfile
import io
import imageio
import numpy as np

# --- Page Configuration ---
st.set_page_config(page_title="Vevo 2100 Frame Editor", layout="centered")
st.title("Vevo 2100 Video Editor (Batch)")

st.markdown("""
**Instructions:**
1. **Upload** your videos (GIFs recommended for exact frame syncing).
2. **Select Video**: Choose which video to preview.
3. **Trim**: Set your start/end points.
4. **Split-Pane Crop**: Box out the B-mode and NLC panes. The app will stitch them together.
5. **Format & Order**: Set your export settings and arrange your videos in the sidebar.
6. **Process**: Generate a ZIP of individual files, OR a single merged Grid GIF.
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
    
    # --- 0. Optimize: Cache Temp Files in Session State ---
    if 'temp_video_paths' not in st.session_state:
        st.session_state.temp_video_paths = {}

    current_file_names = [f.name for f in uploaded_files]

    # Cleanup removed files from cache
    for name in list(st.session_state.temp_video_paths.keys()):
        if name not in current_file_names:
            try: os.unlink(st.session_state.temp_video_paths[name])
            except: pass
            del st.session_state.temp_video_paths[name]

    # Create temp files for newly uploaded files only
    for f in uploaded_files:
        if f.name not in st.session_state.temp_video_paths:
            tfile = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(f.name)[1])
            f.seek(0)
            tfile.write(f.read())
            tfile.close()
            st.session_state.temp_video_paths[f.name] = tfile.name

    # --- 1. Video Selector & Mapping ---
    file_map = {f.name: f for f in uploaded_files}
    file_names = list(file_map.keys())
    
    selected_name = st.selectbox("Select Video to Preview/Setup", file_names)
    selected_video_path = st.session_state.temp_video_paths[selected_name]

    # --- 2. Read Metadata ---
    cap = cv2.VideoCapture(selected_video_path)
    
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
    
    max_display_frame = total_frames
    min_display_frame = 1
    
    st.sidebar.caption(f"Total Frames: {total_frames}")

    if 'current_video_name' not in st.session_state or st.session_state.current_video_name != selected_name:
        st.session_state.current_video_name = selected_name
        st.session_state.num_start = 1
        st.session_state.num_end = total_frames
        st.session_state.slider_range = (1, total_frames)
        st.session_state.preview_frame = 1
        st.session_state.last_start = 1
        st.session_state.last_end = total_frames

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
    
    actual_start = clamp(start_display - 1, 0, total_frames - 1)
    actual_end = clamp(end_display - 1, 0, total_frames - 1)
    
    st.sidebar.info(f"Duration: {actual_end - actual_start + 1} frames")

    # --- 5. Split-Pane Spatial Cropping ---
    st.sidebar.subheader("3. Split-Pane Crop")
    
    # Helper function to sync slider and text box for crop values
    def create_synced_crop(label, key_base, default_val):
        if key_base not in st.session_state:
            st.session_state[key_base] = default_val
            
        def update_slider():
            st.session_state[key_base] = st.session_state[f"{key_base}_slider"]
        def update_num():
            st.session_state[key_base] = st.session_state[f"{key_base}_num"]
            
        st.number_input(label, min_value=0.0, max_value=1.0, value=st.session_state[key_base], step=0.01, format="%.2f", key=f"{key_base}_num", on_change=update_num)
        st.slider(label, min_value=0.0, max_value=1.0, value=st.session_state[key_base], step=0.01, key=f"{key_base}_slider", on_change=update_slider, label_visibility="collapsed")
        return st.session_state[key_base]
    
    st.sidebar.markdown("**Global Height**")
    c1, c2 = st.sidebar.columns(2)
    with c1: y0 = create_synced_crop("Top (%)", "crop_y0", 0.33)
    with c2: y1 = create_synced_crop("Bottom (%)", "crop_y1", 0.49)

    st.sidebar.markdown("**Left Image (B-Mode)**")
    c3, c4 = st.sidebar.columns(2)
    with c3: lx0 = create_synced_crop("L-Start (%)", "crop_lx0", 0.07)
    with c4: lx1 = create_synced_crop("L-End (%)", "crop_lx1", 0.42)

    st.sidebar.markdown("**Right Image (NLC)**")
    c5, c6 = st.sidebar.columns(2)
    with c5: rx0 = create_synced_crop("R-Start (%)", "crop_rx0", 0.52)
    with c6: rx1 = create_synced_crop("R-End (%)", "crop_rx1", 0.88)

    y_start = int(clamp(y0, 0, 1) * H)
    y_end   = int(clamp(y1, 0, 1) * H)
    lx_start = int(clamp(lx0, 0, 1) * W)
    lx_end   = int(clamp(lx1, 0, 1) * W)
    rx_start = int(clamp(rx0, 0, 1) * W)
    rx_end   = int(clamp(rx1, 0, 1) * W)

    if y_end <= y_start: y_end = y_start + 1
    if lx_end <= lx_start: lx_end = lx_start + 1
    if rx_end <= rx_start: rx_end = rx_start + 1

    crop_h = y_end - y_start
    crop_w_left = lx_end - lx_start
    crop_w_right = rx_end - rx_start
    final_w = crop_w_left + crop_w_right

    # --- 6. Export Format Selection & Grid Ordering ---
    st.sidebar.subheader("4. Export Options")
    export_format = st.sidebar.radio("Choose format for individual ZIP export:", ["MP4", "GIF"])
    
    st.sidebar.markdown("**Grid & Ordering (For Merged Export)**")
    ordered_files = st.sidebar.multiselect(
        "Arrange video sequence (Top to Bottom):",
        options=file_names,
        default=file_names,
        help="Click the 'X' to remove a video, or click the empty space to add it back in the order you want."
    )
    grid_cols = st.sidebar.number_input("Grid Columns (Set to 1 for vertical stack)", min_value=1, max_value=10, value=1)

    # --- 7. Interactive Preview ---
    st.subheader(f"Preview: {selected_name}")
    
    if 'preview_frame' not in st.session_state:
        st.session_state.preview_frame = 1

    # Callback functions to sync the slider and the number input
    def update_preview_from_slider():
        st.session_state.preview_frame = st.session_state.preview_slider_ui
    def update_preview_from_num():
        st.session_state.preview_frame = st.session_state.preview_num_ui

    col_scrub1, col_scrub2 = st.columns([3, 1])
    with col_scrub1:
        st.slider(
            "Scrub Timeline", 
            min_value=min_display_frame, 
            max_value=max_display_frame, 
            value=st.session_state.preview_frame,
            step=1,
            key="preview_slider_ui",
            on_change=update_preview_from_slider
        )
    with col_scrub2:
        st.number_input(
            "Go to Frame",
            min_value=min_display_frame, 
            max_value=max_display_frame, 
            value=st.session_state.preview_frame,
            step=1,
            key="preview_num_ui",
            on_change=update_preview_from_num
        )

    preview_frame_display = st.session_state.preview_frame
    actual_preview_frame = clamp(preview_frame_display - 1, 0, total_frames - 1)
    
    # Read frame for the single selected video
    cap.set(cv2.CAP_PROP_POS_FRAMES, actual_preview_frame)
    ret, frame_preview = cap.read()

    if ret:
        current_time = actual_preview_frame / user_fps
        overlay = frame_preview.copy()
        
        cv2.rectangle(overlay, (lx_start, y_start), (lx_end, y_end), (0, 255, 0), 2)
        cv2.rectangle(overlay, (rx_start, y_start), (rx_end, y_end), (0, 255, 0), 2)
        
        st.image(
            cv2.cvtColor(overlay, cv2.COLOR_BGR2RGB), 
            use_container_width=True, 
            caption=f"Frame: {preview_frame_display} | Vevo Time: {current_time:.3f}s"
        )
        
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
                        
                        crop_left = frame_p[y_start:y_end, lx_start:lx_end]
                        crop_right = frame_p[y_start:y_end, rx_start:rx_end]
                        
                        if crop_left.shape[0] > 0 and crop_right.shape[0] > 0:
                            stitched_frame = cv2.hconcat([crop_left, crop_right])
                            preview_writer.write(stitched_frame)
                            
                    preview_writer.release()
                    st.video(t_prev.name)
                    
        with col_btn2:
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

        # --- Grid Preview of Current Frame ---
        st.markdown("### Grid Preview at Current Frame")
        if ordered_files:
            caps_grid = []
            for fname in ordered_files:
                path = st.session_state.temp_video_paths[fname]
                cap_obj = cv2.VideoCapture(path)
                cap_obj.set(cv2.CAP_PROP_POS_FRAMES, actual_preview_frame)
                caps_grid.append(cap_obj)

            num_vids = len(caps_grid)
            rows = (num_vids + grid_cols - 1) // grid_cols
            row_images = []
            
            for r in range(rows):
                cols_in_row = []
                for c in range(grid_cols):
                    idx = r * grid_cols + c
                    if idx < num_vids:
                        ok, frame = caps_grid[idx].read()
                        if ok and frame.shape[0] >= y_end and frame.shape[1] >= max(lx_end, rx_end):
                            cl = frame[y_start:y_end, lx_start:lx_end]
                            cr = frame[y_start:y_end, rx_start:rx_end]
                            if cl.shape[0] > 0 and cr.shape[0] > 0:
                                stitched = cv2.hconcat([cl, cr])
                                cols_in_row.append(stitched)
                            else:
                                cols_in_row.append(np.zeros((crop_h, final_w, 3), dtype=np.uint8))
                        else:
                            cols_in_row.append(np.zeros((crop_h, final_w, 3), dtype=np.uint8))
                    else:
                        cols_in_row.append(np.zeros((crop_h, final_w, 3), dtype=np.uint8))
                
                row_images.append(cv2.hconcat(cols_in_row))
            
            if row_images:
                full_grid_frame = cv2.vconcat(row_images)
                st.image(
                    cv2.cvtColor(full_grid_frame, cv2.COLOR_BGR2RGB), 
                    use_container_width=True, 
                    caption=f"Overlapped Grid Preview (Frame {preview_frame_display})"
                )
                
                # --- NEW: Grid Frame Download Button ---
                is_success_grid, buffer_grid = cv2.imencode(".png", full_grid_frame)
                if is_success_grid:
                    st.download_button(
                        label="📸 Download Grid Frame",
                        data=buffer_grid.tobytes(),
                        file_name=f"grid_preview_frame_{preview_frame_display}.png",
                        mime="image/png"
                    )
            
            for cap_obj in caps_grid:
                cap_obj.release()
        else:
            st.info("No videos selected in the 'Arrange video sequence' options to form a grid.")

    else:
        st.warning("Could not read frame.")
    
    cap.release()

    st.markdown("---")

    # --- 8. Processing Section ---
    st.subheader("Batch Processing Options")
    col_process_zip, col_process_grid = st.columns(2)

    # --- OPTION A: Original ZIP Logic ---
    if 'processed_zip' not in st.session_state:
        st.session_state['processed_zip'] = None

    with col_process_zip:
        if st.button(f"📦 Export to ZIP\n({len(uploaded_files)} videos as {export_format})"):
            progress_bar = st.progress(0.0)
            status_text = st.empty()
            zip_buffer = io.BytesIO()
            
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
                for i, uploaded_file in enumerate(uploaded_files):
                    status_text.text(f"Zipping {uploaded_file.name}...")
                    
                    t_in_name = st.session_state.temp_video_paths[uploaded_file.name]

                    vcap = cv2.VideoCapture(t_in_name)
                    vcap.set(cv2.CAP_PROP_POS_FRAMES, actual_start)
                    base_name = os.path.splitext(uploaded_file.name)[0]
                    
                    ext = ".mp4" if export_format == "MP4" else ".gif"
                    out_name = f"{base_name}_frames_{start_display}-{end_display}{ext}"
                    
                    t_out = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
                    t_out_name = t_out.name
                    t_out.close()
                    
                    if export_format == "MP4":
                        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                        writer = cv2.VideoWriter(t_out_name, fourcc, user_fps, (final_w, crop_h))
                    else:
                        writer = imageio.get_writer(t_out_name, mode='I', fps=user_fps, loop=0)
                    
                    for _ in range(actual_start, actual_end + 1):
                        ok, frame = vcap.read()
                        if not ok: break
                        
                        if frame.shape[0] >= y_end and frame.shape[1] >= max(lx_end, rx_end):
                            crop_left = frame[y_start:y_end, lx_start:lx_end]
                            crop_right = frame[y_start:y_end, rx_start:rx_end]
                            
                            if crop_left.shape[0] > 0 and crop_right.shape[0] > 0:
                                stitched_frame = cv2.hconcat([crop_left, crop_right])
                                
                                if export_format == "MP4":
                                    writer.write(stitched_frame)
                                else:
                                    rgb_frame = cv2.cvtColor(stitched_frame, cv2.COLOR_BGR2RGB)
                                    writer.append_data(rgb_frame)
                    
                    vcap.release()
                    
                    if export_format == "MP4": writer.release()
                    else: writer.close()
                        
                    zipf.write(t_out_name, arcname=out_name)
                    try: os.unlink(t_out_name)
                    except: pass
                    progress_bar.progress((i + 1) / len(uploaded_files))

            status_text.success("✅ ZIP Complete!")
            zip_buffer.seek(0)
            st.session_state['processed_zip'] = zip_buffer.getvalue()

    # --- OPTION B: Merged Grid Logic ---
    if 'merged_grid_gif' not in st.session_state:
        st.session_state['merged_grid_gif'] = None

    with col_process_grid:
        if st.button(f"🎬 Export Overlapped Grid\n(Stack ordered files on 1 .gif screen)"):
            if not ordered_files:
                st.error("Please select at least one video in the Grid Options.")
            else:
                with st.spinner("Stitching videos into single grid GIF..."):
                    caps = []
                    
                    for fname in ordered_files:
                        path = st.session_state.temp_video_paths[fname]
                        cap_obj = cv2.VideoCapture(path)
                        cap_obj.set(cv2.CAP_PROP_POS_FRAMES, actual_start)
                        caps.append(cap_obj)

                    num_vids = len(caps)
                    rows = (num_vids + grid_cols - 1) // grid_cols
                    
                    t_grid_out = tempfile.NamedTemporaryFile(delete=False, suffix=".gif")
                    grid_writer = imageio.get_writer(t_grid_out.name, mode='I', fps=user_fps, loop=0)

                    progress_bar_grid = st.progress(0.0)
                    total_frames_to_process = actual_end - actual_start + 1

                    for step, f_idx in enumerate(range(actual_start, actual_end + 1)):
                        row_images = []
                        for r in range(rows):
                            cols_in_row = []
                            for c in range(grid_cols):
                                idx = r * grid_cols + c
                                if idx < num_vids:
                                    ok, frame = caps[idx].read()
                                    if ok and frame.shape[0] >= y_end and frame.shape[1] >= max(lx_end, rx_end):
                                        cl = frame[y_start:y_end, lx_start:lx_end]
                                        cr = frame[y_start:y_end, rx_start:rx_end]
                                        if cl.shape[0] > 0 and cr.shape[0] > 0:
                                            stitched = cv2.hconcat([cl, cr])
                                            cols_in_row.append(stitched)
                                        else:
                                            cols_in_row.append(np.zeros((crop_h, final_w, 3), dtype=np.uint8))
                                    else:
                                        cols_in_row.append(np.zeros((crop_h, final_w, 3), dtype=np.uint8))
                                else:
                                    cols_in_row.append(np.zeros((crop_h, final_w, 3), dtype=np.uint8))
                            
                            row_images.append(cv2.hconcat(cols_in_row))
                        
                        full_grid_frame = cv2.vconcat(row_images)
                        rgb_grid_frame = cv2.cvtColor(full_grid_frame, cv2.COLOR_BGR2RGB)
                        grid_writer.append_data(rgb_grid_frame)
                        
                        progress_bar_grid.progress((step + 1) / total_frames_to_process)

                    grid_writer.close()
                    for cap_obj in caps: cap_obj.release()

                    with open(t_grid_out.name, "rb") as f:
                        st.session_state['merged_grid_gif'] = f.read()
                    try: os.unlink(t_grid_out.name)
                    except: pass

                    st.success("✅ Overlapped Grid Complete!")

    # --- Render Download Buttons ---
    st.markdown("---")
    col_dl1, col_dl2 = st.columns(2)
    
    with col_dl1:
        if st.session_state['processed_zip'] is not None:
            st.download_button(
                label="⬇️ Download ZIP",
                data=st.session_state['processed_zip'],
                file_name="vevo_processed_videos.zip",
                mime="application/zip"
            )

    with col_dl2:
        if st.session_state['merged_grid_gif'] is not None:
            st.download_button(
                label="⬇️ Download Overlapped Grid (.gif)",
                data=st.session_state['merged_grid_gif'],
                file_name="vevo_merged_grid.gif",
                mime="image/gif"
            )

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
1. **Upload** your videos.
2. **Setup**: Use the sidebar to set global crop and trim settings.
3. **Arrange**: Use the "Video Ordering" section to decide how they appear in the merged video.
4. **Process**: Download individual files or a single merged grid video.
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
    file_map = {f.name: f for f in uploaded_files}
    file_names = list(file_map.keys())
    
    # --- 1. Video Selector for Preview ---
    selected_name = st.selectbox("Select Video to Preview/Setup", file_names)
    selected_file = file_map[selected_name]

    # --- 2. Read Metadata ---
    tfile = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(selected_file.name)[1])
    selected_file.seek(0)
    tfile.write(selected_file.read())
    tfile.flush()
    
    cap = cv2.VideoCapture(tfile.name)
    if not cap.isOpened():
        total_frames, detected_fps, W, H = 100, 30.0, 640, 480
    else:
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        detected_fps = cap.get(cv2.CAP_PROP_FPS)
        W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if total_frames <= 0: total_frames = 100
        if detected_fps <= 0: detected_fps = 30.0

    # --- SIDEBAR SETTINGS ---
    st.sidebar.header("Processing Settings")

    # 1. FPS
    user_fps = st.sidebar.number_input("Capture FPS", 1.0, 1000.0, float(detected_fps))
    
    # 2. Trim
    st.sidebar.subheader("2. Trim Video")
    if 'current_video_name' not in st.session_state or st.session_state.current_video_name != selected_name:
        st.session_state.current_video_name = selected_name
        st.session_state.num_start, st.session_state.num_end = 1, total_frames
        st.session_state.slider_range = (1, total_frames)
        st.session_state.preview_frame = 1

    def update_sync():
        s, e = st.session_state.slider_range
        st.session_state.num_start, st.session_state.num_end = s, e

    col_start, col_end = st.sidebar.columns(2)
    start_display = col_start.number_input("Start", 1, total_frames, key="num_start")
    end_display = col_end.number_input("End", 1, total_frames, key="num_end")
    st.sidebar.slider("Range", 1, total_frames, value=(start_display, end_display), key="slider_range", on_change=update_sync)
    
    actual_start, actual_end = start_display - 1, end_display - 1

    # 3. Crop
    st.sidebar.subheader("3. Split-Pane Crop")
    y0 = st.sidebar.slider("Top (%)", 0.0, 1.0, 0.33)
    y1 = st.sidebar.slider("Bottom (%)", 0.0, 1.0, 0.49)
    lx0, lx1 = st.sidebar.columns(2)
    lx_s = lx0.slider("L-Start", 0.0, 1.0, 0.07)
    lx_e = lx1.slider("L-End", 0.0, 1.0, 0.42)
    rx0, rx1 = st.sidebar.columns(2)
    rx_s = rx0.slider("R-Start", 0.0, 1.0, 0.52)
    rx_e = rx1.slider("R-End", 0.0, 1.0, 0.88)

    y_start, y_end = int(y0 * H), int(y1 * H)
    lx_start, lx_end = int(lx_s * W), int(lx_e * W)
    rx_start, rx_end = int(rx_s * W), int(rx_e * W)
    crop_h, final_w = (y_end - y_start), (lx_end - lx_start) + (rx_end - rx_start)

    # 4. Format
    export_format = st.sidebar.radio("Export Format", ["MP4", "GIF"])

    # 5. Arrange Videos (New Feature)
    st.sidebar.subheader("5. Multi-Video Grid")
    ordered_files = st.sidebar.multiselect(
        "Arrange order for Merged Video:", 
        options=file_names, 
        default=file_names,
        help="The order here determines the sequence in the merged grid."
    )
    grid_cols = st.sidebar.number_input("Grid Columns", 1, 10, value=1)

    # --- Preview Logic ---
    st.subheader(f"Preview: {selected_name}")
    preview_frame_display = st.slider("Scrub", 1, total_frames, value=st.session_state.preview_frame)
    cap.set(cv2.CAP_PROP_POS_FRAMES, preview_frame_display - 1)
    ret, frame_preview = cap.read()

    if ret:
        overlay = frame_preview.copy()
        cv2.rectangle(overlay, (lx_start, y_start), (lx_end, y_end), (0, 255, 0), 2)
        cv2.rectangle(overlay, (rx_start, y_start), (rx_end, y_end), (0, 255, 0), 2)
        st.image(cv2.cvtColor(overlay, cv2.COLOR_BGR2RGB), use_container_width=True)

    # --- Processing ---
    st.markdown("---")
    col_proc1, col_proc2 = st.columns(2)

    # Button 1: Batch Process
    if col_proc1.button(f"📦 Process All ({len(uploaded_files)})"):
        # ... [Keep your existing batch logic here for individual files] ...
        st.info("Individual files processed. (Logic omitted for brevity, remains unchanged from your snippet)")

    # Button 2: Merge into One Video (New Feature)
    if col_proc2.button("🎬 Create Merged Grid Video"):
        if not ordered_files:
            st.error("Please select videos in the sidebar to arrange them.")
        else:
            with st.spinner("Stitching videos into grid..."):
                # Setup temp inputs
                temp_paths = []
                caps = []
                for name in ordered_files:
                    f = file_map[name]
                    f.seek(0)
                    t_in = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(f.name)[1])
                    t_in.write(f.read())
                    t_in.close()
                    temp_paths.append(t_in.name)
                    caps.append(cv2.VideoCapture(t_in.name))

                # Calculate Grid dimensions
                num_vids = len(ordered_files)
                rows = (num_vids + grid_cols - 1) // grid_cols
                canvas_w = grid_cols * final_w
                canvas_h = rows * crop_h

                ext = ".mp4" if export_format == "MP4" else ".gif"
                t_merged = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
                
                if export_format == "MP4":
                    writer = cv2.VideoWriter(t_merged.name, cv2.VideoWriter_fourcc(*'mp4v'), user_fps, (canvas_w, canvas_h))
                else:
                    writer = imageio.get_writer(t_merged.name, mode='I', fps=user_fps, loop=0)

                for f_idx in range(actual_start, actual_end + 1):
                    row_images = []
                    for r in range(rows):
                        cols_in_row = []
                        for c in range(grid_cols):
                            idx = r * grid_cols + c
                            if idx < num_vids:
                                caps[idx].set(cv2.CAP_PROP_POS_FRAMES, f_idx)
                                success, frame = caps[idx].read()
                                if success:
                                    c_l = frame[y_start:y_end, lx_start:lx_end]
                                    c_r = frame[y_start:y_end, rx_start:rx_end]
                                    stitched = cv2.hconcat([c_l, c_r])
                                    cols_in_row.append(stitched)
                                else:
                                    cols_in_row.append(np.zeros((crop_h, final_w, 3), dtype=np.uint8))
                            else:
                                cols_in_row.append(np.zeros((crop_h, final_w, 3), dtype=np.uint8))
                        row_images.append(cv2.hconcat(cols_in_row))
                    
                    full_canvas = cv2.vconcat(row_images)
                    if export_format == "MP4":
                        writer.write(full_canvas)
                    else:
                        writer.append_data(cv2.cvtColor(full_canvas, cv2.COLOR_BGR2RGB))

                if export_format == "MP4": writer.release()
                else: writer.close()
                for c in caps: c.release()
                for p in temp_paths: os.unlink(p)

                with open(t_merged.name, "rb") as f:
                    st.download_button("⬇️ Download Merged Video", f.read(), f"merged_vevo{ext}")
    
    cap.release()
    try: os.unlink(tfile.name)
    except: pass

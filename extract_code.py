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
2. **Set FPS**: Input the frame rate used during capture.
3. **Trim & Crop**: Adjust the slider and green box.
4. **Process**: Click process to generate the files.
5. **Download**: A persistent download button will appear once done.
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
    # --- 1. Initialize Preview (First Video) ---
    # Save the first uploaded file to temp to read metadata
    tfile = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_files[0].name)[1])
    tfile.write(uploaded_files[0].read())
    tfile.flush()
    
    cap = cv2.VideoCapture(tfile.name)
    if not cap.isOpened():
        st.error("Error opening video file.")
    else:
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        detected_fps = cap.get(cv2.CAP_PROP_FPS)
        W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        # Fallback for missing metadata
        if total_frames <= 0: total_frames = 100
        if detected_fps <= 0: detected_fps = 30.0
        if W == 0 or H == 0: 
            ret, first_frame = cap.read()
            if ret:
                H, W = first_frame.shape[:2]

    st.sidebar.header("Processing Settings")

    # --- 2. FPS Input ---
    st.sidebar.subheader("1. Playback Speed")
    user_fps = st.sidebar.number_input(
        "Capture FPS", 
        min_value=1.0, 
        max_value=1000.0, 
        value=float(detected_fps), 
        step=1.0,
        help="Enter the frame rate used to capture the video."
    )

    # --- 3. Frame Trimming ---
    st.sidebar.subheader("2. Trim Video (by Frames)")
    
    start_f, end_f = st.sidebar.slider(
        "Select Frame Range",
        min_value=0,
        max_value=total_frames - 1,
        value=(0, total_frames - 1),
        step=1
    )
    
    st.sidebar.info(f"Keeping frames **{start_f}** to **{end_f}**\n(Duration: {end_f - start_f + 1} frames)")

    # --- 4. Spatial Cropping ---
    st.sidebar.subheader("3. Spatial Crop")
    
    # Default Vevo 2100 crop values
    default_x0, default_x1 = 0.00, 1.00
    default_y0, default_y1 = 0.21, 0.55

    c1, c2 = st.sidebar.columns(2)
    with c1:
        x0 = st.slider("Left (%)", 0.0, 1.0, default_x0, 0.01)
        x1 = st.slider("Right (%)", 0.0, 1.0, default_x1, 0.01)
    with c2:
        y0 = st.slider("Top (%)", 0.0, 1.0, default_y0, 0.01)
        y1 = st.slider("Bottom (%)", 0.0, 1.0, default_y1, 0.01)

    # Calculate pixel coordinates
    x_start = int(clamp(x0, 0, 1) * W)
    x_end   = int(clamp(x1, 0, 1) * W)
    y_start = int(clamp(y0, 0, 1) * H)
    y_end   = int(clamp(y1, 0, 1) * H)

    if x_end <= x_start: x_end = x_start + 1
    if y_end <= y_start: y_end = y_start + 1
    crop_w = x_end - x_start
    crop_h = y_end - y_start

    # --- 5. Interactive Preview ---
    st.subheader(f"Preview: {uploaded_files[0].name}")
    
    preview_frame_idx = st.slider(
        "Scrub Timeline to Verify Crop", 
        min_value=0, 
        max_value=total_frames - 1, 
        value=start_f,
        step=1
    )

    cap.set(cv2.CAP_PROP_POS_FRAMES, preview_frame_idx)
    ret, frame_preview = cap.read()

    if ret:
        overlay = frame_preview.copy()
        cv2.rectangle(overlay, (x_start, y_start), (x_end, y_end), (0, 255, 0), 2)
        st.image(cv2.cvtColor(overlay, cv2.COLOR_BGR2RGB), use_column_width=True, caption=f"Frame: {preview_frame_idx}")
    
    cap.release()
    # Clean up temp preview file
    try:
        os.unlink(tfile.name)
    except:
        pass

    st.markdown("---")

    # --- 6. Batch Processing Logic ---
    
    # Initialize session state for the zip file if it doesn't exist
    if 'processed_zip' not in st.session_state:
        st.session_state['processed_zip'] = None

    if st.button(f"Process {len(uploaded_files)} Video(s)"):
        
        progress_bar = st.progress(0.0)
        status_text = st.empty()
        
        # Buffer for ZIP file
        zip_buffer = io.BytesIO()
        
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
            
            for i, uploaded_file in enumerate(uploaded_files):
                status_text.text(f"Processing {uploaded_file.name}...")
                
                # 1. Write input to temp
                uploaded_file.seek(0)
                t_in = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[1])
                t_in.write(uploaded_file.read())
                t_in.flush()
                t_in.close()

                # 2. Setup Video Capture
                vcap = cv2.VideoCapture(t_in.name)
                
                # 3. Setup Video Writer
                base_name = os.path.splitext(uploaded_file.name)[0]
                out_name = f"{base_name}_frames_{start_f}-{end_f}.mp4"
                
                t_out = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
                t_out_name = t_out.name
                t_out.close()
                
                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                writer = cv2.VideoWriter(t_out_name, fourcc, user_fps, (crop_w, crop_h))
                
                # 4. Loop Frames
                current_frame = 0
                while True:
                    ok, frame = vcap.read()
                    if not ok:
                        break
                    
                    if start_f <= current_frame <= end_f:
                        crop = frame[y_start:y_end, x_start:x_end]
                        if crop.shape[0] > 0 and crop.shape[1] > 0:
                            writer.write(crop)
                    
                    current_frame += 1
                    if current_frame > end_f:
                        break
                
                # 5. Cleanup current file
                vcap.release()
                writer.release()
                
                try:
                    os.unlink(t_in.name)
                except:
                    pass
                
                # 6. Add to Zip
                zipf.write(t_out_name, arcname=out_name)
                
                try:
                    os.unlink(t_out_name)
                except:
                    pass
                
                # Update Progress
                progress_bar.progress((i + 1) / len(uploaded_files))

        status_text.success("✅ Processing Complete!")
        
        # Save zip to session state
        zip_buffer.seek(0)
        st.session_state['processed_zip'] = zip_buffer.getvalue()

    # --- 7. Persistent Download Button ---
    if st.session_state['processed_zip'] is not None:
        st.download_button(
            label="⬇️ Download All Processed Videos (ZIP)",
            data=st.session_state['processed_zip'],
            file_name="vevo_processed_videos.zip",
            mime="application/zip"
        )

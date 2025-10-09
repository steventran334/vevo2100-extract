import streamlit as st
import cv2
import numpy as np
import tempfile
import os

st.set_page_config(page_title="Vevo 2100 Batch Cropper", layout="centered")
st.title("Vevo 2100 Video Cropper (Batch Mode)")

st.markdown("""
Upload one or more **Vevo 2100** videos below.  
The app crops the **top band across the full width** (adjustable) and exports cropped versions with `_cropped` added to each filename.
""")

uploaded_files = st.file_uploader(
    "Upload video(s) (.mp4, .avi, .mov)", type=["mp4", "avi", "mov"], accept_multiple_files=True
)

def clamp(val, lo, hi):
    return max(lo, min(hi, val))

if uploaded_files:
    # Read first video to get frame dimensions for slider defaults
    tmp_preview = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_files[0].name)[1])
    tmp_preview.write(uploaded_files[0].read())
    tmp_preview.flush()
    cap_preview = cv2.VideoCapture(tmp_preview.name)
    ok, first_frame = cap_preview.read()
    cap_preview.release()
    if not ok:
        st.error("Could not read preview frame.")
        st.stop()

    H, W = first_frame.shape[:2]

    # --- Default ROI (percentages) ---
    default_x0 = 0.00
    default_x1 = 1.00
    default_y0 = 0.21
    default_y1 = 0.55

    st.subheader("Crop settings (percent of frame)")
    c1, c2 = st.columns(2)
    with c1:
        x0 = st.slider("Left (x₀)", 0.0, 1.0, default_x0, 0.001)
        x1 = st.slider("Right (x₁)", 0.0, 1.0, default_x1, 0.001)
    with c2:
        y0 = st.slider("Top (y₀)", 0.0, 1.0, default_y0, 0.001)
        y1 = st.slider("Bottom (y₁)", 0.0, 1.0, default_y1, 0.001)

    # Compute pixel coordinates
    x_start = int(round(clamp(x0, 0, 1) * W))
    x_end   = int(round(clamp(x1, 0, 1) * W))
    y_start = int(round(clamp(y0, 0, 1) * H))
    y_end   = int(round(clamp(y1, 0, 1) * H))
    crop_w = x_end - x_start
    crop_h = y_end - y_start

    overlay = first_frame.copy()
    cv2.rectangle(overlay, (x_start, y_start), (x_end, y_end), (0, 255, 255), 2)
    st.caption("Preview (first frame with crop overlay)")
    st.image(cv2.cvtColor(overlay, cv2.COLOR_BGR2RGB), use_column_width=True)

    st.markdown("---")

    if st.button("Process All Uploaded Videos"):
        output_files = []
        for uploaded in uploaded_files:
            # Rewind file pointer
            uploaded.seek(0)
            tmp_in = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded.name)[1])
            tmp_in.write(uploaded.read())
            tmp_in.flush()

            cap = cv2.VideoCapture(tmp_in.name)
            if not cap.isOpened():
                st.error(f"Could not open {uploaded.name}")
                continue

            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

            # Construct output filename
            base, ext = os.path.splitext(uploaded.name)
            cropped_name = f"{base}_cropped{ext}"

            tmp_out = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(tmp_out.name, fourcc, fps, (crop_w, crop_h))

            prog = st.progress(0.0, text=f"Processing {uploaded.name}")
            i = 0
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                crop = frame[y_start:y_end, x_start:x_end]
                writer.write(crop)
                i += 1
                if total > 0:
                    prog.progress(min(1.0, i / total), text=f"{uploaded.name}: {i}/{total} frames")

            writer.release()
            cap.release()
            os.unlink(tmp_in.name)
            output_files.append((cropped_name, tmp_out.name))

        st.success("✅ All videos processed successfully!")

        for name, path in output_files:
            with open(path, "rb") as f:
                st.download_button(
                    label=f"Download {name}",
                    data=f,
                    file_name=name,
                    mime="video/mp4",
                )

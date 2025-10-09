import streamlit as st
import cv2
import numpy as np
import tempfile
import os

st.set_page_config(page_title="Vevo 2100 Cropper", layout="centered")
st.title("Vevo 2100 Video Cropper")

st.markdown(
    "Upload your Vevo 2100 video. The app crops the **top band across the full width** "
    "as in your annotated screenshot. Adjust if needed, preview, then export."
)

uploaded = st.file_uploader("Upload video (.mp4/.avi/.mov)", type=["mp4", "avi", "mov"])

def clamp(val, lo, hi):
    return max(lo, min(hi, val))

if uploaded:
    # Save upload to a temp file for OpenCV
    tmp_in = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded.name)[1])
    tmp_in.write(uploaded.read())
    tmp_in.flush()

    cap = cv2.VideoCapture(tmp_in.name)
    if not cap.isOpened():
        st.error("Could not open video. Is the file valid?")
    else:
        # Read first frame for preview & dimension reference
        ok, first = cap.read()
        if not ok:
            st.error("Could not read first frame.")
            cap.release()
            os.unlink(tmp_in.name)
            st.stop()

        H, W = first.shape[:2]

        # --- Default ROI (percentages) tuned to your annotated image ---
        # Full width; top band taking roughly the top 33–40% of the frame.
        # Adjust these if your export UI margins differ.
        default_x0 = 0.00
        default_x1 = 1.00
        default_y0 = 0.08
        default_y1 = 0.40

        st.subheader("Crop settings (percent of frame)")
        c1, c2 = st.columns(2)
        with c1:
            x0 = st.slider("Left (x₀)", 0.0, 1.0, default_x0, 0.001)
            x1 = st.slider("Right (x₁)", 0.0, 1.0, default_x1, 0.001)
        with c2:
            y0 = st.slider("Top (y₀)", 0.0, 1.0, default_y0, 0.001)
            y1 = st.slider("Bottom (y₁)", 0.0, 1.0, default_y1, 0.001)

        # Ensure valid ordering
        if x1 <= x0 or y1 <= y0:
            st.warning("Right must be > Left and Bottom must be > Top.")
            st.stop()

        # Compute integer pixel ROI from percentages
        x_start = int(round(clamp(x0, 0, 1) * W))
        x_end   = int(round(clamp(x1, 0, 1) * W))
        y_start = int(round(clamp(y0, 0, 1) * H))
        y_end   = int(round(clamp(y1, 0, 1) * H))

        # Make width/height even to avoid codec issues
        crop_w = (x_end - x_start)
        crop_h = (y_end - y_start)
        if crop_w <= 0 or crop_h <= 0:
            st.error("Crop width/height computed as zero or negative. Adjust sliders.")
            st.stop()
        if crop_w % 2 == 1:
            x_end -= 1
            crop_w -= 1
        if crop_h % 2 == 1:
            y_end -= 1
            crop_h -= 1

        # Preview overlay & cropped first frame
        overlay = first.copy()
        cv2.rectangle(overlay, (x_start, y_start), (x_end, y_end), (0, 255, 255), 2)
        st.caption("Preview (first frame with crop overlay)")
        st.image(cv2.cvtColor(overlay, cv2.COLOR_BGR2RGB), use_column_width=True)

        preview_crop = first[y_start:y_end, x_start:x_end]
        st.caption("Cropped first frame")
        st.image(cv2.cvtColor(preview_crop, cv2.COLOR_BGR2RGB), use_column_width=True)

        st.markdown("---")
        if st.button("Process & Export Cropped Video"):
            # Prepare output writer
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")  # widely supported
            tmp_out = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
            writer = cv2.VideoWriter(tmp_out.name, fourcc, fps, (crop_w, crop_h))

            # Reset to frame 0
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

            prog = st.progress(0.0)
            i = 0
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                crop = frame[y_start:y_end, x_start:x_end]
                writer.write(crop)
                i += 1
                if total > 0:
                    prog.progress(min(1.0, i / total))
            writer.release()
            cap.release()

            st.success("Done! Download your cropped video below.")
            with open(tmp_out.name, "rb") as f:
                st.download_button(
                    "Download cropped video (MP4)",
                    data=f,
                    file_name="cropped_vevo2100.mp4",
                    mime="video/mp4",
                )

            # Clean up temp input after offering download
            os.unlink(tmp_in.name)
        else:
            # Keep cap open for another run; release only on export or reload
            pass

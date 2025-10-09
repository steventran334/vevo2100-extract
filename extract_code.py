import streamlit as st
import cv2
import tempfile
import numpy as np
import os
from moviepy.editor import VideoFileClip

st.title("Vevo 2100 Video Cropper")

st.markdown("""
Upload your **Vevo 2100** video below.  
This app will automatically crop the ultrasound ROI region (same as shown in your example images).
""")

uploaded_video = st.file_uploader("Upload Vevo 2100 video", type=["mp4", "avi", "mov"])

if uploaded_video:
    # Save uploaded video temporarily
    temp_input = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    temp_input.write(uploaded_video.read())
    temp_input.flush()

    # Open video with OpenCV
    cap = cv2.VideoCapture(temp_input.name)
    if not cap.isOpened():
        st.error("Error opening video file.")
    else:
        # --- Fixed crop region (based on example images) ---
        # Adjust if needed depending on your Vevo export resolution
        # Example images roughly correspond to 208x368 video frame
        # Crop rectangle chosen to capture the three bright circular ROIs
        x, y, w, h = 40, 90, 280, 110   # <-- tweak these if crop area differs

        # Get FPS and frame size
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        # Prepare output file
        temp_output = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(temp_output.name, fourcc, fps, (w, h))

        st.write("Processing video...")
        progress = st.progress(0)
        for i in range(total_frames):
            ret, frame = cap.read()
            if not ret:
                break
            cropped = frame[y:y+h, x:x+w]
            out.write(cropped)
            progress.progress((i+1)/total_frames)
        cap.release()
        out.release()

        st.success("Cropping complete ✅")

        # Show preview (first frame)
        cap_preview = cv2.VideoCapture(temp_output.name)
        ret, preview_frame = cap_preview.read()
        if ret:
            st.image(cv2.cvtColor(preview_frame, cv2.COLOR_BGR2RGB), caption="Preview of cropped video")
        cap_preview.release()

        # Offer download
        with open(temp_output.name, "rb") as f:
            st.download_button(
                label="Download Cropped Video",
                data=f,
                file_name="cropped_vevo2100.mp4",
                mime="video/mp4"
            )

    # Cleanup temporary input when done
    os.unlink(temp_input.name)

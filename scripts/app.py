import argparse
import os

import streamlit as st
from PIL import Image
from dotenv import load_dotenv

load_dotenv()
from cad3dify import generate_step_from_2d_cad_image


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model_type", type=str, default="gpt")
    return parser.parse_args()


args = parse_args()

st.title("2D图纸 to 3DCAD")

uploaded_file = st.sidebar.file_uploader("请选择图片文件", type=["jpg", "jpeg", "png"])

# 上传图片后显示
if uploaded_file is not None:
    image = Image.open(uploaded_file)
    ext = os.path.splitext(uploaded_file.name)[1]
    st.image(image, caption="已上传的图片", width="stretch")
    st.write("图片尺寸: ", image.size)
    with open(f"temp.{ext}", "wb") as f:
        f.write(uploaded_file.getbuffer())
    with st.spinner("正在处理图片..."):
        generate_step_from_2d_cad_image(
            f"temp.{ext}", "output.step", model_type=args.model_type
        )
    st.success("3DCAD 数据生成完成。")
else:
    st.write("尚未上传图片。")

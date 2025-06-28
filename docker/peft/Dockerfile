# v0.1.0 was:
# FROM nvidia/cuda:12.2.0-base-ubuntu22.04
# v0.2.0 is:
FROM nvidia/cuda:12.2.2-base-ubuntu22.04

RUN apt-get update && apt-get install -y \
    && apt-get install git wget nano rsync python3-enchant pip -y \
    && apt-get install libportaudio2 libportaudiocpp0 portaudio19-dev libasound-dev libsndfile1-dev ffmpeg cuda-toolkit-12-2 -y \
    && pip3 install pyaudio

RUN pip3 install -U pip

RUN pip3 install bitsandbytes
RUN pip3 install git+https://github.com/huggingface/transformers.git
RUN pip3 install git+https://github.com/huggingface/peft.git
RUN pip3 install git+https://github.com/huggingface/accelerate.git
RUN pip3 install datasets
RUN pip3 install torch
RUN pip3 install peft
RUN pip3 install scipy
RUN pip3 install jupyterlab
RUN pip3 install ipywidgets
RUN pip3 install sentencepiece
RUN pip3 install protobuf
RUN pip3 install flash-attn --no-build-isolation
RUN pip3 install trl
RUN pip3 install wandb
RUN pip3 install xmltodict
RUN pip3 install xmlschema
RUN pip3 install scikit-learn

RUN pip3 install tiktoken
RUN pip3 install openai
RUN pip3 install autoawq

RUN pip3 install groq
RUN pip3 install google-generativeai
RUN pip3 install trl

RUN pip3 install auto-round
RUN pip3 install optimum
RUN pip3 install auto-gptq

CMD [ "/bin/bash" ]
# FOR lupin:0.8.0
#FROM python:3.10.12
FROM nvidia/cuda:12.2.2-base-ubuntu22.04

# Install build dependencies and Python 3.11.5 from source
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        wget \
        zlib1g-dev \
        libncurses5-dev \
        libgdbm-dev \
        libnss3-dev \
        libssl-dev \
        libreadline-dev \
        libffi-dev \
        libsqlite3-dev \
        libbz2-dev \
        liblzma-dev \
        tk-dev && \
    wget https://www.python.org/ftp/python/3.11.5/Python-3.11.5.tgz && \
    tar -xzf Python-3.11.5.tgz && \
    cd Python-3.11.5 && \
    ./configure --enable-optimizations && \
    make -j"$(nproc)" && \
    make altinstall && \
    cd .. && \
    rm -rf Python-3.11.5 Python-3.11.5.tgz && \
    apt-get purge -y build-essential wget && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# Ensure 'python3' and 'pip3' point to the new 3.11.5 install
RUN ln -sf /usr/local/bin/python3.11 /usr/bin/python3 && \
    ln -sf /usr/local/bin/pip3.11 /usr/bin/pip3

# Install everything else
RUN apt-get update && apt-get install -y \
    && apt-get install cuda-toolkit-12-2 -y \
    && apt-get install git wget nano rsync python3-enchant pip -y \
    && apt-get install libportaudio2 libportaudiocpp0 portaudio19-dev libasound-dev libsndfile1-dev ffmpeg -y \
    && pip install pyaudio

RUN pip install -U pip

#######################################
# Specific versions needed to support web socket Io
#######################################
#RUN pip install Flask==2.1.3
#RUN pip install Flask-SocketIO==5.0.1
#RUN pip install eventlet==0.30.2
#RUN pip install Werkzeug==2.0.3
#RUN pip install requests==2.31.0

RUN pip install pandas

RUN pip install pydub

RUN pip install pyperclip

# RUN pip install flask_cors

# RUN #pip install duckduckgo-search

# RUN pip install jupyterlab
#
# RUN pip install ipywidgets

RUN pip install tabulate

RUN pip install tiktoken

RUN pip install --upgrade --no-cache-dir openai

# RUN pip install --upgrade --no-cache-dir langchain[llms]

# RUN pip install --upgrade --no-cache-dir wandb

RUN pip install --upgrade --no-cache-dir transformers

RUN pip install --upgrade --no-cache-dir accelerate

RUN pip install --upgrade --no-cache-dir torch

RUN pip install pyaudio

RUN pip install huggingface_hub

RUN pip install --no-cache-dir wheel packaging ninja
ENV MAX_JOBS=12
RUN pip install flash-attn --no-build-isolation

RUN python3 -c "from huggingface_hub import snapshot_download; snapshot_download( repo_id='distil-whisper/distil-large-v3' )"

RUN pip install xmlschema

RUN pip install scikit-learn

RUN pip install autoawq

RUN pip install --no-cache-dir groq google-generativeai

RUN pip install --no-cache-dir lancedb kagiapi tantivy

RUN pip install --no-cache-dir fastapi

RUN pip install --no-cache-dir spacy[lookups]

RUN python3 -m spacy download en_core_web_sm

RUN apt-get update && apt-get install -y curl

RUN pip install pydantic-ai[slim]==0.2.5

env LUPIN_ROOT=/var/lupin

env LUPIN_CONFIG_MGR_CLI_ARGS="config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Development" \

WORKDIR=/var/lupin/src
RUN mkdir -p /var/io

CMD ["/bin/bash", "-c", "echo '-- OR -- Run `python3 -m fastapi_app.main` to spin up FastAPI server' && exec /bin/bash"]

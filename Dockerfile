# Azure ML doesn't have CUDA 12.1 base images, so use Ubuntu 22.04
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    wget \
    build-essential \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgeos-dev \
    && rm -rf /var/lib/apt/lists/*

# Install CUDA Toolkit 12.1 for flash-attn compilation
RUN wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-keyring_1.1-1_all.deb && \
    dpkg -i cuda-keyring_1.1-1_all.deb && \
    apt-get update && \
    apt-get install -y cuda-toolkit-12-1 && \
    rm -rf /var/lib/apt/lists/* cuda-keyring_1.1-1_all.deb

# Set CUDA environment variables
ENV CUDA_HOME=/usr/local/cuda-12.1
ENV PATH=${CUDA_HOME}/bin:${PATH}
ENV LD_LIBRARY_PATH=${CUDA_HOME}/lib64:${LD_LIBRARY_PATH}

# Install Miniconda
RUN wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O /tmp/miniconda.sh && \
    bash /tmp/miniconda.sh -b -p /opt/conda && \
    rm /tmp/miniconda.sh
ENV PATH=/opt/conda/bin:$PATH

# Accept conda Terms of Service
RUN conda config --set notify_outdated_conda false && \
    conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main && \
    conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r

# Create conda environment from SimLingo's environment.yaml (mounted from local src/simlingo/)
WORKDIR /workspace
RUN --mount=type=bind,source=.,target=/tmp/simlingo \
    conda env create -f /tmp/simlingo/environment.yaml

# Make conda environment available
SHELL ["conda", "run", "-n", "simlingo", "/bin/bash", "-c"]

# Install PyTorch 2.2.0 separately to ensure correct CUDA version (per SimLingo setup)
RUN pip install torch==2.2.0

# Install flash-attn separately (required by SimLingo)
RUN pip install flash-attn==2.7.0.post2

# Activate conda environment on container start
RUN echo "conda activate simlingo" >> ~/.bashrc
ENV PATH=/opt/conda/envs/simlingo/bin:$PATH

# Set entrypoint
ENTRYPOINT ["/bin/bash"]
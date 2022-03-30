FROM ubuntu:focal

RUN apt update
RUN apt install -y python3-pip

COPY . /etc/chameleon_image_tools
RUN pip3 install wheel
RUN pip3 install -r /etc/chameleon_image_tools/requirements.txt

WORKDIR /etc/chameleon_image_tools
RUN python3 setup.py install

FROM python:alpine
RUN pip install sanic humanreadable manuf
WORKDIR /usr/local/lib/python3.13/site-packages/manuf
RUN rm -fv manuf
RUN wget https://www.wireshark.org/download/automated/data/manuf -O manuf
RUN echo -en '52:54:00\tQEMU\tQEMU/KVM virtual machine\n' >> manuf
ADD aio_api_ros /aio_api_ros
WORKDIR /aio_api_ros
RUN pip install .
ADD mikrotik.py /mikrotik.py
ENTRYPOINT /mikrotik.py
EXPOSE 3001

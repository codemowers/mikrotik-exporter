FROM python:3.14-alpine
RUN pip install sanic humanreadable manuf
WORKDIR /usr/local/lib/python3.14/site-packages/manuf
RUN wget https://www.wireshark.org/download/automated/data/manuf -O manuf.upstream
RUN echo -en '52:54:00\tQEMU\tQEMU/KVM virtual machine\n' > manuf
RUN cat manuf.upstream >> manuf
RUN rm -f manuf.upstream
ADD aio_api_ros /aio_api_ros
WORKDIR /aio_api_ros
RUN pip install .
ADD mikrotik.py /mikrotik.py
ENTRYPOINT /mikrotik.py
EXPOSE 3001

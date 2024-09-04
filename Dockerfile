FROM python:alpine
RUN wget https://standards-oui.ieee.org/oui/oui.txt -O /var/lib/ouilookup
RUN pip install sanic humanreadable mac-vendor-lookup
ADD aio_api_ros /aio_api_ros
WORKDIR /aio_api_ros
RUN pip install .
ADD mikrotik.py /mikrotik.py
ENTRYPOINT /mikrotik.py
EXPOSE 3001

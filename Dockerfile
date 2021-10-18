FROM python:3
RUN pip install aiostream sanic
ADD aio_api_ros /aio_api_ros
WORKDIR /aio_api_ros
RUN pip install .
ADD mikrotik.py /mikrotik.py
ENTRYPOINT /mikrotik.py
EXPOSE 3001

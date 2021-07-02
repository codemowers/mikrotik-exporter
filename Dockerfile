FROM python:3
RUN pip install aiostream sanic git+https://github.com/laurivosandi/aio_api_ros
ADD mikrotik.py /mikrotik.py
ENTRYPOINT /mikrotik.py
EXPOSE 3001

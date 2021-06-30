FROM python:3
RUN pip install aio_api_ros aiostream sanic
ADD mikrotik.py /mikrotik.py
ENTRYPOINT /mikrotik.py
EXPOSE 3001

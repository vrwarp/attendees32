FROM postgis/postgis:13-3.5

# age encrypts the backups to the recovery sheet's key; rclone copies them to the bucket.
RUN apt-get update && apt-get install --no-install-recommends -y age rclone \
    && rm -rf /var/lib/apt/lists/*

COPY ./compose/production/postgres/maintenance /usr/local/bin/maintenance
RUN chmod +x /usr/local/bin/maintenance/*
RUN mv /usr/local/bin/maintenance/* /usr/local/bin \
    && rmdir /usr/local/bin/maintenance

FROM python:3.7.1-alpine

RUN apk add --no-cache --update \
    bash \
    build-base \
    patch \
    ca-certificates \
    git \
    bzip2-dev \
    linux-headers \
    ncurses-dev \
    openssl \
    openssl-dev \
    readline-dev \
    sqlite-dev \
    libffi-dev \
    && update-ca-certificates && rm -rf /var/cache/apk/*

# add a non-root user and give them ownership
RUN adduser -D -u 9000 app && \
    # repo
    mkdir /repo && \
    chown -R app:app /repo && \
    # app code
    mkdir -p /usr/src/app && \
    chown -R app:app /usr/src/app

WORKDIR /usr/src/app

# install an initial version of pipenv, which Pipfile.lock will overwite with
# a more specific version
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
RUN pip install --upgrade pip
RUN pip install pipenv
ADD Pipfile Pipfile.lock /usr/src/app/
RUN pipenv install --system

# add the pullrequest utility to easily create pull requests on different git hosts
ENV DEPS_VERSION=2.4.1
RUN wget https://github.com/dependencies-io/deps/releases/download/${DEPS_VERSION}/deps_${DEPS_VERSION}_linux_amd64.tar.gz && \
    mkdir deps && \
    tar -zxvf deps_${DEPS_VERSION}_linux_amd64.tar.gz -C deps && \
    ln -s /usr/src/app/deps/deps /usr/local/bin/deps

# run everything from here on as non-root
USER app

# install pyenv for managing more python versions and switching
RUN git clone --depth 1 https://github.com/pyenv/pyenv.git /usr/src/app/pyenv
ENV PYENV_ROOT="/usr/src/app/pyenv"
ENV PATH="$PYENV_ROOT/shims:$PYENV_ROOT/bin:$PATH"

# install these common versions ahead of time
RUN pyenv install 3.6.6
RUN pyenv install 2.7.15

RUN git config --global user.email "bot@dependencies.io"
RUN git config --global user.name "Dependencies.io Bot"

ADD src/ /usr/src/app/

ENTRYPOINT ["./entrypoint.sh"]

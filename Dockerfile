FROM python:3.7.2-alpine

RUN apk add --no-cache --update \
    bash \
    curl \
    build-base \
    patch \
    ca-certificates \
    git \
    bzip2-dev \
    linux-headers \
    ncurses-dev \
    readline-dev \
    sqlite-dev \
    libffi-dev \
    zlib-dev \
    postgresql-dev \
    && update-ca-certificates

ENV LIBRARY_PATH=/lib:/usr/lib

RUN mkdir -p /usr/src/app
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
ENV DEPS_VERSION=2.5.0-beta.2
RUN curl https://www.dependencies.io/install.sh | bash -s -- -b /usr/local/bin $DEPS_VERSION

# install pyenv for managing more python versions and switching
RUN git clone --depth 1 https://github.com/pyenv/pyenv.git /usr/src/app/pyenv
ENV PYENV_ROOT="/usr/src/app/pyenv"
ENV PATH="$PYENV_ROOT/shims:$PYENV_ROOT/bin:$PATH"

# install these common versions ahead of time
RUN pyenv install 3.6.6
RUN pyenv install 2.7.15

RUN git config --system user.email "bot@dependencies.io"
RUN git config --system user.name "Dependencies.io Bot"

ADD src/ /usr/src/app/

ENTRYPOINT ["./entrypoint.sh"]

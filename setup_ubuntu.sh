sudo apt-get install --force-yes -y make libudev-dev g++ libyaml-dev python3-pip
pip3 install virtualenv
virtualenv --python=python3 venv
source venv/bin/activate
pip3 install python_openzwave
pip3 install cython wheel six
pip3 install influxdb

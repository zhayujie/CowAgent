#!/bin/bash

unset KUBECONFIG

cd .. && docker build -f docker/Dockerfile.latest \
             -t zhayujie/cowagent .

docker tag zhayujie/cowagent zhayujie/cowagent:$(date +%y%m%d)
# Legacy name, still published and pulled by existing deployments
docker tag zhayujie/cowagent zhayujie/chatgpt-on-wechat
docker tag zhayujie/cowagent zhayujie/chatgpt-on-wechat:$(date +%y%m%d)
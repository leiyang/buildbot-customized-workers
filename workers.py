from __future__ import absolute_import, division, print_function

import json
import os
import random
import string

from buildbot.plugins import worker, util
from pprint import pprint


class MyWorkerBase(object):
    # true if this box is buildbot.net, and can build docs, etc.
    buildbot_net = False

    # true if this box should use a 'simple' factory, meaning no virtualenv
    # (basically good for windows)
    use_simple = False

    # true if this box can test the buildmaster and worker, respectively
    test_master = True
    test_worker = True

    # true if this worker should have a single-worker builder of its own
    run_single = True

    # true if this host has PyQt4 installed in its default python
    pyqt4 = False

    # true if this worker can contribute to the virtualenv-managed pool of
    # specific-configuration builders.  Specific supported python versions
    # are given, too
    run_config = False
    py26 = False
    py27 = False
    pypy17 = False
    pypy18 = False

    tw0810 = False
    tw0900 = True
    tw1020 = True
    tw1110 = True
    tw1220 = True
    tw1320 = True
    tw1400 = True

    # true if this has nodejs installed, suitable for www
    nodejs = False

    # dictionary mapping databases to the env vars required to make them go
    databases = {}

    # operating system, for os-specific builders; this should only be used
    # for fleets of machines that are basically interchangebale
    os = None

    def extract_attrs(self, name, **kwargs):
        self.name = name
        remaining = {}
        for k in kwargs:
            if hasattr(self, k):
                setattr(self, k, kwargs[k])
            else:
                remaining[k] = kwargs[k]
        return remaining

    def get_random_pass(self):
        return ''.join(
            random.choice(string.ascii_uppercase + string.digits)
            for _ in range(20))

    def get_pass(self, name):
        # get the password based on the name
        path = os.path.join(os.path.dirname(__file__), "%s.pass" % name)
        if not os.path.exists(path):
            print("warning {} does not exit. creating one".format(path))
            pw = self.get_random_pass()
            with open(path, 'w') as f:
                f.write(pw)

        pw = open(path).read().strip()
        return pw

    def get_ec2_creds(self, name):
        path = os.path.join(os.path.dirname(__file__), "%s.ec2" % name)
        return open(path).read().strip().split(" ")



from buildbot.interfaces import LatentWorkerFailedToSubstantiate
from buildbot.util import kubeclientservice
from twisted.internet import defer
kube_config=util.KubeInClusterConfigLoader()

class MyKubeWorker(MyWorkerBase, worker.KubeLatentWorker):

    def get_pod_spec(self, build):

        cpu = str(build.getProperty("NUM_CPU", "1"))
        mem = str(build.getProperty("MEMORY_SIZE", "1G"))
        image = str(build.getProperty("DOCKER_IMAGE", "buildbot/buildbot-worker:master"))

        # ensure proper configuration
        if mem not in ["256M", "512M", "1G", "2G", "4G"]:
            mem = "1G"
        if cpu not in ["1", "2", "4"]:
            cpu = "1"

        size = build.getProperty("HYPER_SIZE")
        env=self.createEnvironment()
        _d={
            #'WORKERPASS':'pass',
            'WORKER_ENVIRONMENT_BLACKLIST':'DOCKER_BUILDBOT* BUILDBOT_ENV_* BUILDBOT_1* WORKER_ENVIRONMENT_BLACKLIST',
            }

        env.update(_d)

        if size is not None:
            # backward compat for rebuilding old commits
            HYPER_SIZES = {
                "s3": [1, "256M"],
                "s4": [1, "512M"],
                "m1": [1, "1G"],
                "m2": [2, "2G"],
                "m3": [2, "4G"]
            }
            cpu, mem = HYPER_SIZES[size]
            # squeeze a bit more containers
            cpu = cpu*0.7
        return {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": self.getContainerName()
            },
            "spec": {
                "containers": [{
                    "name": self.getContainerName(),
                    "image": image,
                    "ports": [{
                        "containerPort": 9989,
                        "name": "worker"
                    }],
                    "env": [{
                        "name": k,
                        "value": v
                    } for k, v in env.items()],
                    "resources": {
                        "requests": {
                            "cpu": cpu,
                            "memory": mem
                        }
                    }
                }],
                "restartPolicy":
                "Never"
            }
        }
    def __init__(self, name, **kwargs):
        kwargs = self.extract_attrs(name, **kwargs)
        #kube_config=kubeclientservice.KubeInClusterConfigLoader()
        #kube_config.reconfigService()
        #data=kube_config.getConfig()
        #pprint(data)

        worker.KubeLatentWorker.__init__(
            self,
            name,
            kube_config=kube_config,
            image="buildbot/buildbot-worker:master",
            #masterFQDN=worker.KubeLatentWorker.get_fqdn,
            masterFQDN=worker.KubeLatentWorker.get_ip,
            **kwargs)

    # todo: upstream this!
    @defer.inlineCallbacks
    def start_instance(self, build):
        pprint("DDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD")
        yield self.stop_instance(reportFailure=False)
        pod_spec = self.get_pod_spec(build)
        pprint(pod_spec)
        try:
            yield self._kube.createPod(self.namespace, pod_spec)
        except kubeclientservice.KubeError as e:
            raise LatentWorkerFailedToSubstantiate(str(e))
        defer.returnValue(True)

workers = [
    # add 21 kube workers
    MyKubeWorker(
        'kubernetes' + str(i),
        max_builds=1,
        build_wait_timeout=0,
        run_single=False,
        run_config=True,
        py26=True,
        py27=True)
    for i in range(10)
]

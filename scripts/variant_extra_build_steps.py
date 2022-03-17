from swiftclient.client import Connection as swift_conn
import sys

sys.path.append("..")
from utils import helpers


class ExtraSteps:
    def fpga(self, **kwargs):
        # download installation packages from Chameleon object storage
        region = kwargs["region"]
        ip = kwargs["ip"]
        rc = kwargs["rc"]
        ssh_key_file = kwargs["ssh_key_file"]
        ssh_args = kwargs["ssh_args"]

        tmp_fpga_dir = '/tmp/fpga'
        session = helpers.get_auth_session_from_rc(rc)

        if region == 'CHI@TACC':
            objects = ['aocl-rte-16.0.0-1.x86_64.rpm', 'nalla_pcie_16.0.2.tgz']
        elif region == 'CHI@UC':
            objects = ['aocl-pro-rte-17.1.0-240.x86_64.rpm',
                       'QuartusProProgrammerSetup-17.1.0.240-linux.run',
                       'de5a_net_e1.tar.gz']
        else:
            raise RuntimeError('Region incorrect!')
        helpers.run('mkdir -p {}'.format(tmp_fpga_dir))
        helpers.remote_run(
            ip=ip, command='sudo mkdir -p {}'.format(tmp_fpga_dir))

        swift_connection = swift_conn(session=session,
                                      os_options={'region_name': region},
                                      preauthurl=session.get_endpoint(
                                          service_type='object-store',
                                          region_name=region,
                                          interface='public')
                                      )
        for obj in objects:
            print('downloading {}'.format(obj))
            resp_headers, obj_contents = swift_connection.get_object('FPGA', obj)
            with open('{}/{}'.format(tmp_fpga_dir, obj), 'wb') as local:
                local.write(obj_contents)
            if ssh_key_file:
                proc = helpers.run('scp -i {} {} {}/{} cc@{}:'
                                   .format(ssh_key_file,
                                           ' '.join(
                                               ssh_args),
                                           tmp_fpga_dir,
                                           obj, ip))
            else:
                proc = helpers.run(
                    'scp {} {}/{} cc@{}:'.format(' '.join(ssh_args),
                                                 tmp_fpga_dir,
                                                 obj, ip))
            print(' - stdout:\n{}\n - stderr:\n{}\n--------'.format(
                proc.stdout, proc.stderr
            ))
            if proc.returncode != 0:
                raise RuntimeError('scp to remote failed!')
            else:
                helpers.remote_run(
                    ip=ip, command='sudo mv ~/{} {}/'.format(obj, tmp_fpga_dir))
                helpers.remote_run(
                    ip=ip, command='sudo chmod -R 755 {}'.format(tmp_fpga_dir))

        # clean up
        helpers.run('rm -rf {}'.format(tmp_fpga_dir))
        helpers.remote_run(ip=ip, command='sudo ls -la /tmp/fpga')

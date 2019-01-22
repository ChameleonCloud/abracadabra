'''
Schedule Jenkins appliance tests
'''
import argparse
import sys

import jenkinshelper

IMAGE_TEST_MATRIX = {'compute_haswell': ['CC-CentOS7', 'CC-Ubuntu16.04', 'CC-Ubuntu14.04'],
                     'compute_skylake': ['CC-CentOS7', 'CC-Ubuntu16.04', 'CC-Ubuntu14.04'],
                     'compute_haswell_ib': ['CC-CentOS7', 'CC-Ubuntu16.04', 'CC-Ubuntu14.04'],
                     'storage': ['CC-CentOS7', 'CC-Ubuntu16.04', 'CC-Ubuntu14.04'],
                     'storage_hierarchy': ['CC-CentOS7', 'CC-Ubuntu16.04', 'CC-Ubuntu14.04'],
                     'gpu_p100': ['CC-Ubuntu16.04-CUDA8', 'CC-CentOS7-CUDA9', 'CC-Ubuntu16.04-CUDA9'],
                     'gpu_p100_nvlink': ['CC-Ubuntu16.04-CUDA8', 'CC-CentOS7-CUDA9', 'CC-Ubuntu16.04-CUDA9'],
                     'gpu_k80': ['CC-Ubuntu16.04-CUDA8', 'CC-CentOS7-CUDA9', 'CC-Ubuntu16.04-CUDA9'],
                     'gpu_m40': ['CC-Ubuntu16.04-CUDA8', 'CC-CentOS7-CUDA9', 'CC-Ubuntu16.04-CUDA9'],
                     'fpga': ['CC-CentOS7-FPGA'], # two images at two different sites
                     'lowpower_xeon': ['CC-CentOS7', 'CC-Ubuntu16.04', 'CC-Ubuntu14.04'],
                     'atom': ['CC-CentOS7', 'CC-Ubuntu16.04', 'CC-Ubuntu14.04'],
                     'arm64': ['CC-Ubuntu16.04-ARM64']
                     }

COMPLEX_APPLIANCE_TEST = {'hello_world': {'node_type': 'compute_haswell', 'node_cnt': 2},
                          'nfs': {'node_type': 'compute_haswell', 'node_cnt': 3}}

JOB_NAME_FORMAT = 'test-{node_type}-{image_name}'
COMPLEX_JOB_NAME_FORMAT = 'test-complex-{complex_appliance_name}'

def reserve_resource_for_test(jenkins_location, booking_site, node_type, image_name):
    job_name = JOB_NAME_FORMAT.format(node_type=node_type.replace('_', '-'), image_name=image_name.lower())
    if node_type == 'fpga':
        job_name = job_name + '-' + booking_site
    job_config_file = jenkins_location + '/' + jenkinshelper.JENKINS_JOB_CONFIG_FILE.format(job_name=job_name)
    
    cctest_openrc_file = jenkins_location + '/' + jenkinshelper.JENKINS_CCTEST_CREDENTIAL_FILE.format(site=booking_site)
    command = '\n'.join(['#!/bin/bash',
                         'source {cctest_openrc}'.format(cctest_openrc=cctest_openrc_file),
                         'cd tests',
                         './do_test.sh {node_type} {image_name} {{lease_id}}'.format(node_type=node_type,image_name=image_name)])
    
    jenkinshelper.update_env_variables_from_file(cctest_openrc_file)  
    reserve_resource_args = {'booking_site': booking_site,
                             'node_type': node_type,
                             'lease_name_prefix': 'appliance-',
                             'job_name': job_name,
                             'job_config_file': job_config_file,
                             'lease_duration_in_hour': 1,
                             'searching_feq_in_min': 30,
                             'exec_command': command} 
    jenkinshelper.reserve_resource(**reserve_resource_args)
    
def reserve_resource_for_complex_appliance_test(jenkins_location, booking_site, complex_appliance_name, node_type, node_count):
    job_name = COMPLEX_JOB_NAME_FORMAT.format(complex_appliance_name=complex_appliance_name)
    job_config_file = jenkins_location + '/' + jenkinshelper.JENKINS_JOB_CONFIG_FILE.format(job_name=job_name)
    
    cctest_openrc_file = jenkins_location + '/' + jenkinshelper.JENKINS_CCTEST_CREDENTIAL_FILE.format(site=booking_site)
    command = '\n'.join(['#!/bin/bash',
                         'source {cctest_openrc}'.format(cctest_openrc=cctest_openrc_file),
                         'cd complex-appliance-tests',
                         './do_test.sh {complex_appliance_name} {key_name} {{lease_id}}'.format(complex_appliance_name=complex_appliance_name,
                                                                                                key_name=jenkinshelper.SITE_KEY_NAME_MAP[booking_site])])
    
    jenkinshelper.update_env_variables_from_file(cctest_openrc_file)  
    reserve_resource_args = {'booking_site': booking_site,
                             'node_type': node_type,
                             'node_count': node_count,
                             'lease_name_prefix': 'appliance-',
                             'job_name': job_name,
                             'job_config_file': job_config_file,
                             'lease_duration_in_hour': 1,
                             'searching_feq_in_min': 30,
                             'exec_command': command} 
    jenkinshelper.reserve_resource(**reserve_resource_args)

def main(argv=None):
    if argv is None:
        argv = sys.argv

    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument('jenkins_jobs_location', type=str,
        help='Jenkins jobs location')
    parser.add_argument('test_target', type=str,
        help='What do you want to test?')
    
    args = parser.parse_args(argv[1:])
    
    if args.test_target == 'complex':
        for complex_appliance in COMPLEX_APPLIANCE_TEST.keys():
            reserve_resource_for_complex_appliance_test(args.jenkins_jobs_location, 
                                                        'tacc', 
                                                        complex_appliance, 
                                                        COMPLEX_APPLIANCE_TEST[complex_appliance]['node_type'], 
                                                        COMPLEX_APPLIANCE_TEST[complex_appliance]['node_cnt'])
    else:
        node_type = args.test_target
        if args.test_target in IMAGE_TEST_MATRIX:
            for image_name in IMAGE_TEST_MATRIX[node_type]:
                if node_type == 'fpga':
                    reserve_resource_for_test(args.jenkins_jobs_location, 'uc', node_type, image_name)
                reserve_resource_for_test(args.jenkins_jobs_location, 'tacc', node_type, image_name)
        else:
            print('Unknown test target {}'.format(node_type))
        
            
          

if __name__ == '__main__':
    sys.exit(main(sys.argv))
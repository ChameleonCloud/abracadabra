pipeline {
    agent any
    environment {
      HOME = "${env.WORKSPACE}"
      DOCKER_REGISTRY = 'ghcr.io'
      DOCKER_NAMESPACE = 'chameleoncloud'
      DOCKER_REGISTRY_CREDS = credentials('kolla-docker-registry-creds')
    }

    stages {
      stage('docker-setup') {
        steps {
          sh 'docker login --username=$DOCKER_REGISTRY_CREDS_USR --password=$DOCKER_REGISTRY_CREDS_PSW $DOCKER_REGISTRY'
        }
      }
      stage('build-and-publish') {
        steps {
          sh 'docker build -t $DOCKER_REGISTRY/$DOCKER_NAMESPACE/chameleon_image_tools:latest .'
          sh 'docker push $DOCKER_REGISTRY/$DOCKER_NAMESPACE/chameleon_image_tools:latest'
        }
      }
    }
    post {
      always {
        sh 'docker logout $DOCKER_REGISTRY'
      }
    }
}

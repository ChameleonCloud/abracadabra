# Appliance BuildeR And Chameleon AutomateD ABRA

Makes appliances for Chameleon.


## Token to Remote for Auth

Pass a token to use so [`curl` can interact with Glance](https://docs.openstack.org/user-guide/cli-manage-images-curl.html)

```
OS_AUTH_TOKEN=adsfasdfasdfasdf
OS_IMAGE_URL=https://chi.tacc.chameleoncloud.org:9292

curl -i -X POST -H "X-Auth-Token: $OS_AUTH_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{"name": "image-something", "build-os": "centos7"}' \
      $OS_IMAGE_URL/v2/images

IMAGE_PATH=/tmp/tmp.041D6esTHE/common/CC-CentOS7.qcow2
IMAGE_ID=0095012b-fb2e-45ee-86d3-7b2fcf0d14c9

curl -i -X PUT -H "X-Auth-Token: $OS_AUTH_TOKEN" \
      -H "Content-Type: application/octet-stream" \
      --data-binary @$IMAGE_PATH \
      $OS_IMAGE_URL/v2/images/$IMAGE_ID/file
```

Something like those are now available as `hammers.osrest.glance.image_upload_curl` and `image_download_curl` which can be run without any particular environment state.

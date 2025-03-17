# Appliance BuildeR And Chameleon AutomateD ABRA

Makes and tests appliances for Chameleon.

# image_deployer.py

The `image_deployer.py` script is a new (and in development) approach to
downloading images from a central object store and pushing them to Glance
at specific sites.

The script requires a site.yaml file configured with the following
settings:
```
---
image_container: chameleon-supported-images
image_type: qcow2
image_prefix: testing_
scope: prod
image_store_cloud: uc_dev
object_store_url: https://chi.uc.chameleoncloud.org:7480/swift/v1/{the account with the image container, e.g. AUTH_id}
```

The image container for production images is stored in a central
object store and should use the scope `prod` by default.

The image container name is `chameleon-supported-images`.

Individual sites can select an `image_type` of `raw` or `qcow2`
for the image format to deploy. All images should have both
formats in the object store.

The `image_prefix` will be added to images when they are initially
pushed to Glance. After pushing the image, any images with an
existing name will be archived with their build date and then
the `image_prefix` will be removed from the newly pushed images.

The `image_store_cloud` is the location of the site with Glance
where the images should be pushed to. This should contain the
credentials for your cloud in a `clouds.yaml` file for the
OpenStack client.

After installing the dependencies, you can run the tool as follows:
```
python3 site_tools/image_deployer.py --site-yaml ~/site.yaml
```

Additionally you can specify either `--dry-run` to see which images
are available and need syncing or `--debug` if you run into issues
and would like to see debug logging.

This tool will likely be evolving in the near future as it is
utilized for image deployment.

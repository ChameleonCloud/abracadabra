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
image_container: chameleon-images
image_type: qcow2
image_prefix: testing_
scope: prod
image_store_cloud: uc_dev
object_store_url: https://chi.uc.chameleoncloud.org:7480/swift/v1/{the account with the image container, e.g. AUTH_id}
```

The image container for production images is stored in a central
object store and should use the scope `prod` by default.

Individual sites can select an `image_type` of `raw` or `qcow2`
for the image format to deploy. All images should have both
formats in the object store.

After installing the dependencies, you can run the tool as follows:
```
python3 site_tools/image_deployer.py --site-yaml ~/site.yaml
```

Additionally you can specify either `--dry-run` to see which images
are available and need syncing or `--debug` if you run into issues
and would like to see debug logging.

This tool will likely be evolving in the near future as it is
utilized for image deployment.

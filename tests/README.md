# Tests

## Environment/Options

* `--image <image name or ID>`
* `--key-name` - defaults to "default" or env var `KEY_NAME`
* `--key-file` - defaults to `"~/.ssh/id_rsa"` or env var `KEY_FILE`

## Fixtures

* `keystone(request)` - Gets auth data from environment or options
* `image(request, keystone)` - detects OS/variant from image metadata, or explicit options
* `server(request, keystone, image)` - starts instance with image and keyname from options
* `shell(request, server)` - SSH handle for server using keyfile from options

## Filters/Decorators

* `pytest.mark.require_os` - provide OS or list of OS's
* `pytest.mark.require_variant` - provide variant or list of variants

## Examples

```
pytest --image=CC-CentOS7
pytest --image=CC-Ubuntu16.04-CUDA8
```

rm -rf ./dist
rm -rf ./build

pyinstaller \
  --onefile \
  --name TrenchCoat \
  --hidden-import mpremote \
  --hidden-import mpremote.main \
  --hidden-import ipaddress \
  trenchcoat.py

#!/bin/sh -ex

cd "$(dirname "$0")"

STORAGE="$HOME/storage"

#
# Setup 1
#

cp -r storage/* "$STORAGE"/

wl user create User

wl container create container1 --path /container1
wl storage create local storage11 --location "$STORAGE"/storage11 \
    --container container1

wl container create container2 --path /container2
wl storage create local-cached storage21 --location "$STORAGE"/storage21 \
    --container container2

cp ~/.config/wildland/containers/container2.container.yaml "$STORAGE"/storage11/container2.yaml

# we start wildland AND the container at the same time
wl start --container container1

#
# Setup case 2
#

# create another user
wl u create User1

mkdir -p ~/.config/wildland/templates

# storage-template
cat > ~/.config/wildland/templates/simple.template.jinja << EOF
- location: $STORAGE/{{ uuid }}
  read-only: false
  type: local
  manifest-pattern:
    type: glob
    path: /*.{object-type}.yaml
EOF

# containers
wl c create --owner User work-qubesos --title "my work on qubesos" --category /qubesos --storage-template simple
wl c create --owner User work-debian --title "my work on debian" --category /debian --storage-template simple
wl c create --owner User work-wildland --title "my work on wildland" --category /wildland --storage-template simple
wl c create --owner User1 work --title "generalstuff" --category /stuff --storage-template simple

# bridges
wl bridge create --owner User --target-user User1 --target-user-location \
  file://$HOME/.config/wildland/users/User1.user.yaml qubes_share
wl bridge create --owner User --target-user User --target-user-location \
  file://$HOME/.config/wildland/users/User.user.yaml --path /forests/User self_bridge

## forest
wl forest create --owner User simple

# publish containers to forest
wl c publish work-qubesos
wl c publish work-debian
wl c publish work-wildland

# mount forest infra container
wl c mount --manifests-catalog :/forests/User:

# mount all
wl c mount :/forests/User:*:

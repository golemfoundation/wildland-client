#!/bin/sh -ex

cd "$(dirname "$0")"

STORAGE="$HOME/storage"
WL='wl -v'

#
# Setup 1
#

cp -r storage/* "$STORAGE"/

$WL user create User

$WL container create container1 --path /container1
$WL storage create local storage11 --location "$STORAGE"/storage11 \
    --container container1

$WL container create container2 --path /container2
$WL storage create local-cached storage21 --location "$STORAGE"/storage21 \
    --container container2

cp ~/.config/wildland/containers/container2.container.yaml "$STORAGE"/storage11/container2.yaml

# we start wildland AND the container at the same time
$WL start --container container1

#
# Setup case 2
#

# create another user
$WL u create User1

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
$WL c create --owner User work-qubesos --title "my work on qubesos" --category /qubesos --storage-template simple
$WL c create --owner User work-debian --title "my work on debian" --category /debian --storage-template simple
$WL c create --owner User work-wildland --title "my work on wildland" --category /wildland --storage-template simple
$WL c create --owner User1 work --title "generalstuff" --category /stuff --storage-template simple

# bridges
$WL bridge create --owner User --target-user User1 --target-user-location \
  file://$HOME/.config/wildland/users/User1.user.yaml qubes_share
$WL bridge create --owner User --target-user User --target-user-location \
  file://$HOME/.config/wildland/users/User.user.yaml --path /forests/User self_bridge

## forest
$WL forest create --owner User simple

# publish containers to forest
$WL c publish work-qubesos
$WL c publish work-debian
$WL c publish work-wildland

# mount forest infra container
$WL c mount --manifests-catalog :/forests/User:

# mount all
$WL c mount :/forests/User:*:

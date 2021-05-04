#!/bin/sh -ex

cd "$(dirname "$0")"

WL="../../wl"
STORAGE="$HOME/storage"

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
wl u create User1

mkdir -p ~/.config/wildland/templates

# storage-set
cat > ~/.config/wildland/templates/local_title.template.jinja << EOF
location: $STORAGE/{{ uuid }}
read-only: false
type: local
manifest-pattern:
  type: glob
  path: /*.yaml
EOF

cat > ~/.config/wildland/templates/simple.set.yaml << EOF
name: simple
templates:
  - file: local_title.template.jinja
    type: inline
EOF

# containers
wl c create --owner User work-qubesos --title "my work on qubesos" --category /qubesos --storage-set simple
wl c create --owner User work-debian --title "my work on debian" --category /debian --storage-set simple
wl c create --owner User work-wildland --title "my work on wildland" --category /wildland --storage-set simple
wl c create --owner User1 work --title "generalstuff" --category /stuff --storage-set simple

# bridges
wl bridge create --owner User --ref-user User1 --ref-user-location \
  file://$HOME/.config/wildland/users/User1.user.yaml qubes_share
wl bridge create --owner User --ref-user User --ref-user-location \
  file://$HOME/.config/wildland/users/User.user.yaml --ref-user-path /forests/User self_bridge

## forest
wl forest create User simple

# publish containers to forest
wl c publish work-qubesos
wl c publish work-debian
wl c publish work-wildland

# mount forest infra container
wl c mount --infrastructure :/forests/User:

# mount all
wl c mount :/forests/User:*:

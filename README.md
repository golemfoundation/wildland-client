# Wildland Client

Wildland Client is a proof of concept implementation of the new open protocol for data management introduced in the ["Wildland - Why, What and How" paper](https://golem.foundation/resources/documents/wildland-w2h.pdf).

The client has been written in Python, and lets you access data stored with Wildland and serve it as a FUSE based filesystem, which you can then consume with a file manager of your choice.

A live demo of the client, with the lead designer's commentary, is available on our Vimeo channel https://vimeo.com/579474007.

If you would like to try the client yourself, we provide step by step instructions for running it on different systems at https://docs.wildland.io. Please note, however, that **this is a proof of concept, and it is not intended for everyday use**. Its main goal is to showcase three quintessential Wildland features - [backend agnosticism, an infrastructure-independent addressing system and the native multi-categorization of data](https://wildland.io/2021/06/11/introducing-client-v0.1.html).

## Repository structure

* ``Documentation/``: project documentation, in ReST/Sphinx format
* ``ci/``: Docker setup for CI
* ``docker/``: Docker setup for local testing
* ``wl``, ``wildland-cli``: command-line interface entry point
* ``wildland-fuse``: FUSE driver entry point
* ``plugins/``: storage backends source code
* ``wildland/``: Python source code
* ``wildland/schemas/``: Manifest schemas in `JSON Schema <https://json-schema.org/>`format
* ``wildland/tests/``: Tests (in Pytest framework)

## Current status

The Python-built Wildland client is not being developed further. Instead of opptimizing and adding new features to the current Wildland core, we decided to write it anew in Rust. There are several reasons behind this decision. We have learned a lot, not only through developing the Python core, but also by experimenting with various use-cases. This experience has enabled us to identify several ways in which we can improve upon our initial design, especially in terms of user experience, as well as the overall client functionality.

Additionally, Rust has better memory management than Python, and excellent cross-platform capabilities across Linux, macOS, Windows and other major operating systems. Writing the new Wildland core in Rust will thus make it easier for us to develop Wildland-powered apps on different platforms.

To learn more about Wildland and the current status of it's developement, please visit the [Wildland.io webpage](https://wildland.io).

## License

Wildland is an open source project distributed under the terms of the [GNU General Public License](https://www.gnu.org/licenses/gpl-3.0.en.html) as published by the [Free Software Foundation](https://www.fsf.org/), either version 3 of the License, or (at your option) any later version. See [COPYING file](https://gitlab.com/wildland/wildland-client/-/blob/master/COPYING) for the full license text.
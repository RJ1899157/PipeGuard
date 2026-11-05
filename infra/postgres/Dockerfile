ARG TARGETARCH
FROM postgres:17@sha256:31ba9c94a03ada9988f2bb493a22a75eef3a185884533e5cdbcd498ea835b08f AS base
FROM base AS patched-amd64
ADD --checksum=sha256:15c2030e0fb46580af4f1b4cc303f4bd26da781b004e99763bc9eff7cf8e19b8 https://security.debian.org/debian-security/pool/updates/main/a/apt/apt_3.0.4_amd64.deb /tmp/apt.deb
ADD --checksum=sha256:577eb8f489de419290102364892dbd13ca256297b61f96d61b114fd4ac18be41 https://security.debian.org/debian-security/pool/updates/main/a/apt/libapt-pkg7.0_3.0.4_amd64.deb /tmp/libapt-pkg7.0.deb
RUN dpkg --install /tmp/libapt-pkg7.0.deb /tmp/apt.deb && rm /tmp/libapt-pkg7.0.deb /tmp/apt.deb
FROM base AS patched-arm64
ADD --checksum=sha256:9a3ee57117d1d8e086e2d8917cd3e85e8f76da25dd18a898085759668dc5c71f https://security.debian.org/debian-security/pool/updates/main/a/apt/apt_3.0.4_arm64.deb /tmp/apt.deb
ADD --checksum=sha256:39e4d074bc4f2081666a3625561a430fedb0c85b1a6a657c02760383232304bd https://security.debian.org/debian-security/pool/updates/main/a/apt/libapt-pkg7.0_3.0.4_arm64.deb /tmp/libapt-pkg7.0.deb
RUN dpkg --install /tmp/libapt-pkg7.0.deb /tmp/apt.deb && rm /tmp/libapt-pkg7.0.deb /tmp/apt.deb
FROM patched-${TARGETARCH} AS final

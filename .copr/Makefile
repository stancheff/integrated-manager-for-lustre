BUILDROOT:=$(shell [ -d "/build" ] && echo "/build" || echo ".")
TMPDIR:=$(shell mktemp -d)

MFL_COPR_REPO=managerforlustre/manager-for-lustre-5.0
MFL_REPO_OWNER := $(firstword $(subst /, ,$(MFL_COPR_REPO)))
MFL_REPO_NAME  := $(word 2,$(subst /, ,$(MFL_COPR_REPO)))

base.repo: base.repo.in
	sed -e 's/@MFL_COPR_REPO@/$(subst /,\/,$(MFL_COPR_REPO))/g' \
	    -e 's/@MFL_REPO_OWNER@/$(MFL_REPO_OWNER)/g'             \
	    -e 's/@MFL_REPO_NAME@/$(MFL_REPO_NAME)/g' < $< > $@

srpm:
	mkdir -p ${TMPDIR}/_topdir/SOURCES
	mkdir -p ${TMPDIR}/_topdir/SPECS
	mkdir -p ${TMPDIR}/release/rust-iml
	rm -rf ${BUILDROOT}/_topdir
	if ! rpm -q lustre-client 2> /dev/null; then \
		cp lustre-client.repo /etc/yum.repos.d/; \
		yum -y -q install lustre-client;\
	fi
	cargo build --release
	cp target/release/iml-{action-runner,agent,agent-comms,agent-daemon,stratagem,warp-drive} \
		iml-agent-comms.service \
		iml-stratagem.service \
		iml-action-runner.service \
		iml-action-runner.socket \
		iml-agent/systemd-units/* \
		iml-warp-drive/systemd-units/* \
		${TMPDIR}/release/rust-iml
	tar -czvf ${TMPDIR}/_topdir/SOURCES/rust-iml.tar.gz -C ${TMPDIR}/release/rust-iml .
	cp rust-iml.spec ${TMPDIR}/_topdir/SPECS/
	rpmbuild -bs -D "_topdir ${TMPDIR}/_topdir" ${TMPDIR}/_topdir/SPECS/rust-iml.spec
	cp -rf ${TMPDIR}/_topdir ${BUILDROOT}/
	cp -f _topdir/SRPMS/*.rpm $(outdir)

iml-deps:
	yum copr enable -y managerforlustre/buildtools
	yum install -y python2-devel python2-setuptools ed

iml-srpm: iml-deps base.repo
	mkdir -p ${TMPDIR}/_topdir/{SOURCES,SPECS}
	mkdir -p ${TMPDIR}/scratch
	rm -rf ${BUILDROOT}/_topdir

	cp -r ${BUILDROOT}/{chroma_*,chroma-*,__init__.py,manage.py,scm_version.py,setup.py,settings.py,urls.py,wsgi.py,agent-bootstrap-script.template,*.profile} ${TMPDIR}/scratch
	cp -r ${BUILDROOT}/{*.repo,README.*,licenses,polymorphic,scripts,example_storage_plugin_package,tests,MANIFEST.in} ${TMPDIR}/scratch
	cp ${BUILDROOT}/python-iml-manager.spec ${TMPDIR}/_topdir/SPECS
	cp ${BUILDROOT}/iml-*.service \
		${BUILDROOT}/rabbitmq-env.conf \
		${BUILDROOT}/iml-manager-redirect.conf \
		${BUILDROOT}/iml-manager.target \
		${BUILDROOT}/chroma-config.1 \
		${BUILDROOT}/logrotate.cfg \
		${BUILDROOT}/chroma-host-discover-init.sh \
		${TMPDIR}/_topdir/SOURCES

	cd ${TMPDIR}/scratch; \
	python setup.py sdist -d ${TMPDIR}/_topdir/SOURCES/
	
	rpmbuild -bs -D "_topdir ${TMPDIR}/_topdir" ${TMPDIR}/_topdir/SPECS/python-iml-manager.spec

	cp -rf ${TMPDIR}/_topdir ${BUILDROOT}/
	cp -r ${TMPDIR}/_topdir/SRPMS/* $(outdir)
	rm -rf ${TMPDIR}

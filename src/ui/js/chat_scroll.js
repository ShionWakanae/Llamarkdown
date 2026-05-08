(function () {
    let scrollBound = false;
    let observerBound = false;
    let showBtnTimer = null;

    function getArea() {
        return document.querySelector('.chat-area');
    }

    function getBtn() {
        return document.querySelector('.scroll-to-bottom-btn');
    }

    function getClearBtn() {
        return document.querySelector('.floating-clear-btn');
    }

    function getEmptyState() {
        return document.querySelector('.empty-state');
    }

    function getOuterContainer() {
        const area = getArea();
        if (!area) return null;
        return area.closest('.outer-container');
    }

    function scrollToBottom() {
        const area = getArea();

        if (area) {
            area.scrollTo({
                top: area.scrollHeight,
                behavior: 'smooth'
            });
        }
    }

    function updateFadeEffect() {
        const area = getArea();
        if (!area) return;

        const scrollTop = area.scrollTop;
        const scrollHeight = area.scrollHeight;
        const clientHeight = area.clientHeight;
        const maxScroll = scrollHeight - clientHeight;

        if (maxScroll <= 0) {
            const fullVisible = 'linear-gradient(to bottom, black 0%, black 100%)';
            area.style.maskImage = fullVisible;
            area.style.webkitMaskImage = fullVisible;
            return;
        }

        const fadePercent = 6;
        const fadeThreshold = 30;

        const topRatio = Math.min(scrollTop / fadeThreshold, 1);
        const topFade = topRatio * fadePercent;

        const bottomDistance = maxScroll - scrollTop;
        const bottomRatio = Math.min(bottomDistance / fadeThreshold, 1);
        const bottomFade = bottomRatio * fadePercent;

        const maskGradient = 'linear-gradient(to bottom, ' +
            'transparent 0%, ' +
            'black ' + topFade + '%, ' +
            'black ' + (100 - bottomFade) + '%, ' +
            'transparent 100%)';

        area.style.maskImage = maskGradient;
        area.style.webkitMaskImage = maskGradient;
    }

    function updateContainerHeight() {
        const area = getArea();
        const container = getOuterContainer();
        if (!area || !container) return;

        var hasChildren = area.children.length > 0;
        container.style.height = hasChildren ? '100%' : '50%';

        const clearBtn = getClearBtn();
        if (clearBtn) {
            clearBtn.style.opacity = hasChildren ? '0.8' : '0.0';
            clearBtn.style.pointerEvents = hasChildren ? 'auto' : 'none';
        }

        const emptyState = getEmptyState();
        if (emptyState) {
            emptyState.style.opacity = hasChildren ? '0.0' : '1';
        }
    }

    function checkScroll() {

        const area = getArea();
        const btn = getBtn();

        if (!area || !btn) return;

        updateFadeEffect();
        updateContainerHeight();

        const distance =
            area.scrollHeight - area.scrollTop - area.clientHeight;

        const isAtBottom = distance < 100;

        if (isAtBottom) {

            clearTimeout(showBtnTimer);
            showBtnTimer = null;

            btn.style.opacity = '0.0';
            btn.style.pointerEvents = 'none';

            return;
        }

        if (btn.style.opacity === '0.8') {
            return;
        }

        clearTimeout(showBtnTimer);

        showBtnTimer = setTimeout(() => {

            btn.style.opacity = '0.8';
            btn.style.pointerEvents = 'auto';

            showBtnTimer = null;

        }, 300);
    }

    function bindScrollListener() {
        if (scrollBound) return;

        const area = getArea();
        if (!area) return;

        area.addEventListener('scroll', checkScroll, {
            passive: true
        });
        scrollBound = true;
    }

    function observeChatArea() {
        if (observerBound) return;

        const area = getArea();
        if (!area) return;

        const observer = new MutationObserver(function () {
            updateContainerHeight();
            checkScroll();
        });

        observer.observe(area, {
            childList: true,
            subtree: true
        });

        observerBound = true;
    }

    function initWhenReady(retry = 0) {
        const area = getArea();
        const btn = getBtn();

        if ((!area || !btn) && retry < 30) {
            setTimeout(() => initWhenReady(retry + 1), 100);
            return;
        }

        if (!area || !btn) return;

        bindScrollListener();
        observeChatArea();
        updateContainerHeight();
        updateFadeEffect();
        checkScroll();
    }

    document.addEventListener('DOMContentLoaded', () => {
        initWhenReady();
    });

    window.scrollToBottom = scrollToBottom;
    window.checkScroll = checkScroll;
})();

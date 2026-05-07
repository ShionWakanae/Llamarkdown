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

    function scrollToBottom() {
        const area = getArea();

        if (area) {
            area.scrollTo({
                top: area.scrollHeight,
                behavior: 'smooth'
            });
        }
    }

    function checkScroll() {

        const area = getArea();
        const btn = getBtn();

        if (!area || !btn) return;

        const distance =
            area.scrollHeight - area.scrollTop - area.clientHeight;

        const isAtBottom = distance < 100;

        // 到底部：立即隐藏
        if (isAtBottom) {

            clearTimeout(showBtnTimer);
            showBtnTimer = null;

            btn.style.opacity = '0.0';
            btn.style.pointerEvents = 'none';

            return;
        }

        // 已经显示了
        if (btn.style.opacity === '0.8') {
            return;
        }

        // 延迟显示
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

        const observer = new MutationObserver(() => {
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

        // 组件未挂载，最多重试 ~3秒
        if ((!area || !btn) && retry < 30) {
            setTimeout(() => initWhenReady(retry + 1), 100);
            return;
        }

        if (!area || !btn) return;

        bindScrollListener();
        observeChatArea();
        checkScroll();
    }

    // 页面加载后启动
    document.addEventListener('DOMContentLoaded', () => {
        initWhenReady();
    });

    // 暴露给 Python 调用（保持兼容）
    window.scrollToBottom = scrollToBottom;
    window.checkScroll = checkScroll;
})();

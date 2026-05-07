(function () {
        let scrollBound=false;
        let observerBound=false;

        function getArea() {
            return document.querySelector('.chat-area');
        }

        function getBtn() {
            return document.querySelector('.scroll-to-bottom-btn');
        }

        function scrollToBottom() {
            const area=getArea();

            if (area) {
                area.scrollTo({
                    top: area.scrollHeight,
                    behavior: 'smooth'
                });
        }
    }

    function checkScroll() {
        const area=getArea();
        const btn=getBtn();

        if ( !area || !btn) return;

        const isAtBottom=area.scrollHeight - area.scrollTop - area.clientHeight < 20;

        btn.style.display=isAtBottom ? 'none' : 'block';
    }

    function bindScrollListener() {
        if (scrollBound) return;

        const area=getArea();
        if ( !area) return;

        area.addEventListener('scroll', checkScroll, {
            passive: true
        });
        scrollBound=true;
    }

    function observeChatArea() {
        if (observerBound) return;

        const area=getArea();
        if ( !area) return;

        const observer=new MutationObserver(()=> {
                checkScroll();
            });

        observer.observe(area, {
            childList: true,
            subtree: true
        });

        observerBound=true;
    }

    function initWhenReady(retry=0) {
        const area=getArea();
        const btn=getBtn();

        // 组件未挂载，最多重试 ~3秒
        if (( !area || !btn) && retry < 30) {
            setTimeout(()=> initWhenReady(retry + 1), 100);
            return;
        }

        if ( !area || !btn) return;

        bindScrollListener();
        observeChatArea();
        checkScroll();
    }

    // 页面加载后启动
    document.addEventListener('DOMContentLoaded', ()=> {
            initWhenReady();
    });

    // 暴露给 Python 调用（保持兼容）
    window.scrollToBottom=scrollToBottom;
    window.checkScroll=checkScroll;
})();

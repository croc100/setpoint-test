/**
 * theme.js — 다크/라이트 모드 초기화
 *
 * 페이지 로드 시 localStorage에 저장된 테마를 적용합니다.
 * base.html의 인라인 스크립트보다 먼저 실행되어야 하나,
 * <body> 맨 끝에서 로드되므로 초기화는 inline <script>가 담당합니다.
 * 이 파일은 테마 토글 유틸리티 함수를 제공합니다.
 */

(function () {
    'use strict';

    // ── 초기 테마 적용 (FOUC 방지용은 base.html inline <script>에 있음) ──
    function applyTheme(theme) {
        if (theme === 'dark') {
            document.documentElement.classList.add('dark');
        } else {
            document.documentElement.classList.remove('dark');
        }
        document.documentElement.setAttribute('data-theme', theme);
    }

    // 저장된 테마 적용
    var saved = localStorage.getItem('theme');
    if (saved) {
        applyTheme(saved);
    } else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
        applyTheme('dark');
    }

    // 시스템 테마 변경 감지
    if (window.matchMedia) {
        window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function (e) {
            // 사용자가 명시적으로 테마를 선택하지 않은 경우에만 따라감
            if (!localStorage.getItem('theme')) {
                applyTheme(e.matches ? 'dark' : 'light');
            }
        });
    }
})();

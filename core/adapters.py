"""
django-allauth 커스텀 어댑터
- 카카오 소셜 로그인 시 User 필드 자동 처리
"""
import logging
import re
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.account.adapter import DefaultAccountAdapter

logger = logging.getLogger(__name__)


class AccountAdapter(DefaultAccountAdapter):
    """일반 계정 어댑터 - 회원가입 비활성화(소셜 전용)"""

    def is_open_for_signup(self, request):
        # 일반 회원가입 폼은 비활성화 (카카오 로그인만 허용)
        return False


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    """소셜 계정 어댑터 - 카카오 프로필에서 닉네임 추출"""

    def authentication_error(self, request, provider_id, error=None, exception=None, extra_context=None):
        """소셜 로그인 에러 발생 시 상세 로그 출력"""
        logger.error(
            "🔴 카카오 로그인 에러: provider=%s | error=%s | exception=%r | extra=%s",
            provider_id, error, exception, extra_context,
            exc_info=True,
        )
        return super().authentication_error(
            request, provider_id,
            error=error, exception=exception, extra_context=extra_context
        )

    def populate_user(self, request, sociallogin, data):
        user = super().populate_user(request, sociallogin, data)

        # 카카오 extra_data에서 닉네임 추출
        extra = sociallogin.account.extra_data
        kakao_account = extra.get('kakao_account', {})
        profile = kakao_account.get('profile', {})

        nickname = profile.get('nickname', '')
        if nickname:
            user.nickname = nickname
            # username이 비어있으면 닉네임 기반으로 생성
            if not user.username:
                user.username = self._make_username(nickname)

        return user

    def _make_username(self, nickname: str) -> str:
        """닉네임 → 유효한 username으로 변환"""
        from django.contrib.auth import get_user_model
        User = get_user_model()

        base = re.sub(r'[^\w]', '', nickname)[:20] or 'user'
        username = base
        suffix = 1
        while User.objects.filter(username=username).exists():
            username = f'{base}{suffix}'
            suffix += 1
        return username

import pytest

from apps.accounts.models import ClientUser


@pytest.mark.django_db
def test_users_list_shows_only_own_company(signed_in, admin_user, member_user, other_admin):
    emails = {row['email'] for row in signed_in(admin_user).get('/api/users').json()}
    assert emails == {admin_user.email, member_user.email}


@pytest.mark.django_db
def test_member_can_look_but_not_change(signed_in, admin_user, member_user):
    api = signed_in(member_user)
    assert api.get('/api/users').status_code == 200
    assert api.call('patch', f'/api/users/u-{admin_user.pk}', {'role': 'member'}).status_code == 403
    assert api.call('delete', f'/api/users/u-{admin_user.pk}').status_code == 403


@pytest.mark.django_db
def test_admin_changes_role_and_lawyer_box(signed_in, admin_user, member_user):
    response = signed_in(admin_user).call('patch', f'/api/users/u-{member_user.pk}', {'role': 'admin', 'isCounsel': True})
    assert response.json()['role'] == 'admin' and response.json()['isCounsel'] is True


@pytest.mark.django_db
def test_last_admin_cannot_be_demoted(signed_in, admin_user, member_user):
    api = signed_in(admin_user)
    assert api.call('patch', f'/api/users/u-{admin_user.pk}', {'role': 'member'}).status_code == 400


@pytest.mark.django_db
def test_admin_turns_off_a_user(signed_in, admin_user, member_user):
    api = signed_in(admin_user)
    assert api.call('delete', f'/api/users/u-{member_user.pk}').status_code == 204
    member_user.refresh_from_db()
    assert member_user.is_active is False
    assert api.call('delete', f'/api/users/u-{admin_user.pk}').status_code == 400  # not yourself


@pytest.mark.django_db
def test_admin_cannot_touch_another_company(signed_in, admin_user, other_admin):
    api = signed_in(admin_user)
    assert api.call('patch', f'/api/users/u-{other_admin.pk}', {'role': 'member'}).status_code == 404
    assert api.call('delete', f'/api/users/u-{other_admin.pk}').status_code == 404
    assert api.call('delete', '/api/users/u-not-a-number').status_code == 404
    assert ClientUser.objects.get(pk=other_admin.pk).is_active


@pytest.mark.django_db
def test_not_signed_in_gets_401(api):
    assert api.get('/api/users').status_code == 401

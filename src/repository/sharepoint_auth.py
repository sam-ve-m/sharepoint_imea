import json
import requests
from decouple import config
from datetime import datetime
from src.repository.mini_db import MiniDB


class Sharepoint:
    def __init__(
            self,
            site_url=config("site_url"),
            client_id=config("client_id"),
            client_secret=config("client_secret"),
            cache_json_file_name="cache/sharepoint_auth.json",
    ):
        """
        :param site_url:
        :param client_id:
        :param client_secret:
        :param cache_json_file_name: If no cache file is wanted, provide an empty value for this var
        """

        self.site_url = site_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.database = MiniDB(cache_json_file_name)

        self.tenant_id = None
        self.access_token = None
        self.access_token_expiration = 0

    def list_documents(self, folder: str) -> str:
        access_token = self._get_token()
        headers = {"Authorization": "Bearer " + access_token}
        url = f"{self.site_url}/_api/web/GetFolderByServerRelativeUrl('{folder}')"
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.text

    def upload_file(self, file_path: str, content: bytes, folder: str) -> str:
        access_token = self._get_token()
        headers = {"Authorization": "Bearer " + access_token}
        url = f"{self.site_url}/_api/web/GetFolderByServerRelativeUrl('{folder}')/Files/add(url='{file_path}',overwrite=true)"
        response = requests.post(url, headers=headers, data=content)
        response.raise_for_status()
        return response.text

    def download_file(self, folder: str, file: str) -> bytes:
        access_token = self._get_token()
        headers = {"Authorization": "Bearer " + access_token}
        url = f"{self.site_url}/_api/web/GetFolderByServerRelativeUrl('{folder}')/Files('{file}')/$value"
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.content

    def _fetch_tenant_id(self) -> str:
        url = f"{self.site_url}/_vti_bin/client.svc/"
        headers = {
            "User-Agent": "Mozilla/4.0 (compatible; MSIE 6.0; Windows NT 5.0)",
        }
        response = requests.get(url, headers=headers)
        report_to = json.loads(response.headers.get('Report-To'))
        tenant_id = tuple(filter(lambda x: "tenant" in x, report_to.get('endpoints')[0].get('url').split("?")[1].split("&")))[0].split("=")[1]
        assert tenant_id, "Missing tenant id"
        return tenant_id

    def _get_tenant_id(self):
        if not self.tenant_id:
            self.tenant_id = self._search_tenant_id()
        return self.tenant_id

    def _search_tenant_id(self):
        if not (tenant_id := self.database.get('tenant_id')):
            tenant_id = self._fetch_tenant_id()
            self.database.set('tenant_id', tenant_id)
        return tenant_id

    def _generate_token(self) -> tuple:
        tenant_id = self._get_tenant_id()
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        clean_site_url = self.site_url.replace('https://', '').split('/')[0]
        resource = f"00000003-0000-0ff1-ce00-000000000000/{clean_site_url}@{tenant_id}"
        data = {
            "client_id": self.client_id + "@" + tenant_id,
            "resource": resource,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials"
        }
        url = f"https://accounts.accesscontrol.windows.net/{tenant_id}/tokens/OAuth/2"
        response = requests.post(url, headers=headers, data=data)
        response.raise_for_status()
        response_json = response.json()
        return response_json.get('access_token'), float(response_json.get('expires_on'))

    def _search_token(self, time_now: float) -> tuple:
        if time_now > self.database.get('access_token_expiration', 0):
            token, valid_until = self._generate_token()
            self.database.set('access_token_expiration', valid_until)
            self.database.set('access_token', token)
        else:
            token = self.database.get('access_token')
            valid_until = self.database.get('access_token_expiration')
        return token, valid_until

    def _get_token(self) -> str:
        time_now = datetime.now().timestamp()
        if time_now > self.access_token_expiration:
            token, valid_until = self._search_token(time_now)
            self.access_token_expiration = valid_until
            self.access_token = token
        return self.access_token
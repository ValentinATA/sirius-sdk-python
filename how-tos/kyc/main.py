import sirius_sdk
import asyncio


DKMS_NAME = 'test_network'

KYC_AGENT = {
    'server_uri': 'https://demo.socialsirius.com',
    'credentials': b'hpm/U8gtk9RmdsmXovJJPWSIR/+jU1jYB+ysy9tJNRMDFgANbXwBNj/lYtQa0UGEds4aXHHdRWVY0zRd9z1GCXsxLnZKhO+41DO3wMznFaY=',
    'p2p': sirius_sdk.P2PConnection(
            my_keys=('4oPaEqCnEe1Rfj1Hqpa8LhNQrUh9FsuX8XpLUBpeQNFM', '2z3V3YqawWxhnm3iH8tDNt3iCxMaJrKnsmc6FJQUT2GNYa2YgToSPYjG4xMiB9xgMZWry7XZKvNwunVMzDNPNm5V'),
            their_verkey='J2A8STe11Q6tUSznaoodhFWVbUjEG6GkPkQNo7C766BS'
        )
}

KYC_DID = 'Th7MpTaRZVRYnPiabds81Y'
KYC_VERKEY = 'FYmoFw55GeQH7SRFa37dkx1d2dZ3zUF8ckg7wmL7ofN4'


async def register_passport_schema(issuer_did: str) -> (sirius_sdk.CredentialDefinition, sirius_sdk.Schema):
    schema_name = "Passport"

    schema_id, anon_schema = await sirius_sdk.AnonCreds.issuer_create_schema(issuer_did, schema_name, '0.1',
                                         ["full_name", "date_of_birth"])
    l = await sirius_sdk.ledger(DKMS_NAME)
    schema = await l.ensure_schema_exists(anon_schema, issuer_did)
    if not schema:
        ok, schema = await l.register_schema(anon_schema, issuer_did)
        if ok:
            print("Passport schema registered successfully")
        else:
            print("Passport schema was not registered")
            return None, None

    else:
        print("Passport schema is exists in the ledger")

    ok, cred_def = await l.register_cred_def(
        cred_def=sirius_sdk.CredentialDefinition(tag='TAG', schema=schema),
        submitter_did=issuer_did)

    if not ok:
        print("Cred def was not registered")

    return cred_def, schema


if __name__ == '__main__':

    async def run():
        # регистрация формы документа
        async with sirius_sdk.context(**KYC_AGENT):  # работаем от имени агента KYC
            cred_def, schema = await register_passport_schema(KYC_DID)

        # ML магия, результатом которой будут данные паспорта
        credential_values = {
            "full_name": "Mikhail",
            "date_of_birth": "17.03.1993"
        }

        # в случае успеха (данные удалось прочитать с паспорта, паспорт настоящий и фото на нем соответствует лицу с видеопотока)
        # предлагаем пользователю получить его цифровой документ на sirius app

        async with sirius_sdk.context(**KYC_AGENT):  # работаем от имени агента KYC
            connection_key = await sirius_sdk.Crypto.create_key()  # создаем случайный уникальный ключ соединения между агентом и сириус коммуникатором пользователя
            endpoints = await sirius_sdk.endpoints()
            simple_endpoint = [e for e in endpoints if e.routing_keys == []][0]  # точка подключения к агенту (интернет адрес)
            invitation = sirius_sdk.aries_rfc.Invitation(  # Создаем приглашение пользователю подключиться к агенту KYC-сервиса
                label="Invitation to connect with KYC-service",
                recipient_keys=[connection_key],
                endpoint=simple_endpoint.address
            )

            qr_content = invitation.invitation_url
            qr_url = await sirius_sdk.generate_qr_code(qr_content)  # агент генерирует уникальный qr код для ранее созданного приглашения

            # пользователь сканирует qr код при помощи sirius коммуникатора. Коммуникатор отправляет агенту запрос на подключение
            print("Scan this QR by Sirius App for receiving your credentials " + qr_url)

            listener = await sirius_sdk.subscribe()
            async for event in listener:
                if event.recipient_verkey == connection_key and isinstance(event.message, sirius_sdk.aries_rfc.ConnRequest):
                    #  агент получает запрос от пользователя на подключение (запрос соответствует ранее сгенерированному уникальному ключу соединения)
                    request: sirius_sdk.aries_rfc.ConnRequest = event.message
                    #  агент создает уникальный децентрализованный идентификатор (did) для связи с пользователем (который тоже создает уникальный did для этого соединения)
                    my_did, my_verkey = await sirius_sdk.DID.create_and_store_my_did()
                    sm = sirius_sdk.aries_rfc.Inviter(
                        me=sirius_sdk.Pairwise.Me(
                            did=my_did,
                            verkey=my_verkey
                        ),
                        connection_key=connection_key,
                        my_endpoint=simple_endpoint
                    )
                    # Запускается процесс установки соединения в соответствии с протоколом Aries 0160
                    success, p2p = await sm.create_connection(request)
                    if success:
                        # соединение успешно установлено, о чем сообщается пользователю путем отправки простого текстового сообщения на его сириус коммуникатор
                        message = sirius_sdk.aries_rfc.Message(
                            content="Welcome to the KYC-service!",
                            locale="en"
                        )
                        await sirius_sdk.send_to(message, p2p)

                        issuer = sirius_sdk.aries_rfc.Issuer(p2p)
                        preview = [sirius_sdk.aries_rfc.ProposedAttrib(key, str(value)) for key, value in credential_values.items()]
                        translation = [
                            sirius_sdk.aries_rfc.AttribTranslation("full_name", "Full Name"),
                            sirius_sdk.aries_rfc.AttribTranslation("date_of_birth", "Date of birth")
                        ]

                        # KYC-сервис выдает цифровой паспорт пользователю.
                        # Результаты оформлены в соответствии с ранее зареестрированной схемой и подписаны ЦП KYC-сервиса.
                        # Пользователь сохраняет свой цифровой паспорт на своем сириус коммуникаторе
                        ok = await issuer.issue(
                            values=credential_values,
                            schema=schema,
                            cred_def=cred_def,
                            preview=preview,
                            translation=translation,
                            comment="Here is your digital passport",
                            locale="en"
                        )
                        if ok:
                            print("Credentials was issued successfully")
                            # самое всемя удалить всю накопленную инфу о пользователе с сервера


    asyncio.get_event_loop().run_until_complete(run())

## 📚 4. Сценарий лабы

### Запуск добра:
```bash
docker compose up -d
```

![alt text](<images/image1.png>)

Туннель поднялся. Пинг соседа по туннелю:
```bash
docker exec -it branch-a ping 10.0.0.20
### Cтатус IPsec
docker exec -it branch-a ipsec status
```

![alt text](images/image.png)

В выводе ipsec status строка ESTABLISHED 46 seconds ago и INSTALLED, TUNNEL. Это означает, что криптографические ключи успешно согласованы, и IPsec-туннель между филиалом А и филиалом Б поднят. Трафик теперь шифруется (ESP SPIs).

В выводе ping 0% packet loss. Пакеты успешно бегают внутри этого зашифрованного туннеля.

### Демонстрация недостатка (разрыв канала).

Традиционный WAN привязан к конкретным IP/интерфейсам. Чтобы симулировать падение "провайдера", можно просто срубить интерфейс в branch-b или заблокировать трафик через iptables:

```bash
docker exec -it branch-b iptables -I INPUT -s 10.0.0.10 -j DRO
```

![alt text](images/image2.png)

Пинг из пункта 2 повиснет и сдохнет. В SD-WAN система бы заметила потерю пакетов и автоматически перекинула трафик на резервный канал (например, 4G/LTE), а тут у нас тупой статический IPsec, который будет просто лежать и ждать, пока админ (ты) не починит сеть ручками.

### Восстановить можно так

```bash
docker exec -it branch-b iptables -D INPUT -s 10.0.0.10 -j DROP
```
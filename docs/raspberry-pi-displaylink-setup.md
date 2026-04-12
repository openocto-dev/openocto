# Подключение USB-C DisplayLink монитора к Raspberry Pi 5

Инструкция по подключению портативного монитора ASUS MB16ACE (DisplayLink) к Raspberry Pi 5 (Debian 13 trixie, arm64, Wayland/labwc).

Применимо к любым USB-C мониторам на чипе DisplayLink (vendor ID `17e9`).

## Требования

- Raspberry Pi 5 (aarch64, Debian 13 trixie)
- USB-C монитор с DisplayLink (например ASUS MB16ACE / MB16AC)
- Основной монитор по HDMI

## Шаг 1. Проверить, что Pi видит монитор

```bash
lsusb | grep DisplayLink
# Bus 003 Device 005: ID 17e9:4374 DisplayLink MB16AC
```

Если DisplayLink не виден — проверь кабель и USB-порт.

## Шаг 2. Установить Synaptics APT репозиторий

```bash
wget -q "https://www.synaptics.com/sites/default/files/Ubuntu/pool/stable/main/all/synaptics-repository-keyring.deb" -O /tmp/synaptics-repo.deb
sudo dpkg -i /tmp/synaptics-repo.deb
sudo apt-get update
```

## Шаг 3. Установить драйверы

```bash
sudo apt install -y evdi-dkms displaylink-driver
```

Пакет `displaylink-driver` содержит официальный arm64 бинарник DisplayLink Manager v6.2.

## Шаг 4. Заблокировать модуль udl

Модуль `udl` конфликтует с `evdi` и вызывает принудительное клонирование экранов.

```bash
# Заблокировать udl
echo "blacklist udl" | sudo tee /etc/modprobe.d/blacklist-udl.conf

# Убрать udl из зависимостей evdi
sudo tee /etc/modprobe.d/evdi.conf << 'EOF'
softdep evdi pre: drm_dma_helper drm_shmem_helper v3d vc4
options evdi initial_device_count=1
EOF
```

## Шаг 5. Включить программный курсор

DisplayLink/evdi не поддерживает аппаратный курсор — без этой настройки курсор будет невидим на DisplayLink мониторе.

```bash
echo "WLR_NO_HARDWARE_CURSORS=1" >> ~/.config/labwc/environment
```

## Шаг 6. Настроить расположение мониторов (kanshi)

```bash
mkdir -p ~/.config/kanshi
cat > ~/.config/kanshi/config << 'EOF'
profile {
	output HDMI-A-1 enable mode 1920x1080@60.000 position 0,0
	output DVI-I-1 enable mode 1920x1080@60.000 position 1920,0
}

profile {
	output HDMI-A-1 enable mode 1920x1080@60.000 position 0,0
}
EOF
```

Первый профиль — два монитора (HDMI слева, DisplayLink справа).
Второй профиль — только HDMI (fallback когда DisplayLink отключён).

Имена выходов (`HDMI-A-1`, `DVI-I-1`) можно узнать через `wlr-randr`.

## Шаг 7. Перезагрузить

```bash
sudo reboot
```

## Проверка

```bash
# Модули
lsmod | grep -E "evdi|udl"
# Должен быть evdi, НЕ должно быть udl

# Мониторы
export XDG_RUNTIME_DIR=/run/user/$(id -u)
export WAYLAND_DISPLAY=wayland-0
wlr-randr
# Оба монитора Enabled: yes, разные Position
```

## Troubleshooting

### Монитор показывает "Alt DP Mode not supported"

Это нормально при первом подключении до загрузки драйвера. После загрузки ОС и DisplayLink Manager картинка должна появиться.

### Курсор невидим на DisplayLink мониторе

Убедись что `WLR_NO_HARDWARE_CURSORS=1` добавлен в `~/.config/labwc/environment` и перезагрузи.

### Экраны зеркалируются вместо расширения

Заблокируй модуль `udl` (шаг 4) и перезагрузи.

### Мышь не переходит на второй монитор

Проверь позиции через `wlr-randr`. Мониторы должны стыковаться: если HDMI на `0,0` с разрешением 1920x1080, то DisplayLink должен быть на `1920,0`.

### Экран замёрз после отключения/подключения

```bash
sudo systemctl restart displaylink-driver
```

Если не помогло — перезагрузка.

### DisplayLink монитор не может быть единственным дисплеем

Ограничение: labwc (wlroots) не рендерит рабочий стол напрямую на evdi/DisplayLink output. При отключении HDMI монитора DisplayLink экран замрёт. Всегда нужен основной HDMI монитор.

## Зеркалирование (опционально)

Если вместо расширенного рабочего стола нужно зеркалирование:

```bash
sudo apt install -y wl-mirror

# Запуск зеркалирования HDMI на DisplayLink
wl-mirror --fullscreen-output DVI-I-1 -F HDMI-A-1 &
```

Для автозапуска добавить в `~/.config/labwc/autostart`:

```bash
sleep 5 && wl-mirror --fullscreen-output DVI-I-1 -F HDMI-A-1 &
```

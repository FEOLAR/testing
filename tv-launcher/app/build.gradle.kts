plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "space.whitehole.tv"
    compileSdk = 34

    defaultConfig {
        applicationId = "space.whitehole.tv"
        minSdk = 21
        targetSdk = 34
        versionCode = (System.getenv("GITHUB_RUN_NUMBER")?.toIntOrNull() ?: 1)
        versionName = "1.0." + (System.getenv("GITHUB_RUN_NUMBER") ?: "0")
        // Адрес сервера WhiteHole (вход по коду, данные подписки, установка Happ) — один на всё приложение
        buildConfigField("String", "API_BASE", "\"https://77-91-95-53.sslip.io:9443\"")
    }

    buildFeatures {
        buildConfig = true
    }

    // ----- Встроенный VPN (ядро Xray из libv2ray.aar, см. vpn/README.md) -----
    // Отдельные APK под armeabi-v7a и arm64-v8a + универсальный (оба ABI). x86 не собираем.
    splits {
        abi {
            isEnable = true
            reset()
            include("armeabi-v7a", "arm64-v8a")
            isUniversalApk = true
        }
    }
    packaging {
        jniLibs {
            useLegacyPackaging = true // .so сжаты в APK (меньше размер скачивания)
            excludes += listOf("lib/x86/**", "lib/x86_64/**")
        }
    }
    sourceSets {
        // geoip.dat / geosite.dat кладёт CI (vpn/fetch-deps.sh); в git их нет
        getByName("main").assets.srcDir("vpn-assets")
    }
    testOptions {
        unitTests.isReturnDefaultValues = true
    }

    // Ключ подписи хранится в репозитории намеренно (v1, подарочное приложение):
    // стабильный ключ нужен, чтобы обновления ставились поверх старой версии.
    signingConfigs {
        create("release") {
            storeFile = file("whitehole-tv.jks")
            storePassword = "whitehole-tv-2026"
            keyAlias = "whitehole"
            keyPassword = "whitehole-tv-2026"
        }
    }

    buildTypes {
        getByName("release") {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("release")
        }
        getByName("debug") {
            signingConfig = signingConfigs.getByName("release")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    lint {
        abortOnError = false
        checkReleaseBuilds = false
    }
}

dependencies {
    implementation("com.google.zxing:core:3.5.3")
    // AndroidLibXrayLite (2dust) — скачивается в CI скриптом vpn/fetch-deps.sh (версия и sha256 закреплены там)
    implementation(files("libs/libv2ray.aar"))

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303") // настоящий org.json для JVM-тестов (в android.jar — заглушки)
}

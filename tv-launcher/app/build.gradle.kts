plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "space.whitehole.tv"
    compileSdk = 34

    defaultConfig {
        applicationId = "space.whitehole.tv"
        minSdk = 24
        targetSdk = 34
        versionCode = (System.getenv("GITHUB_RUN_NUMBER")?.toIntOrNull() ?: 1)
        versionName = "1.0." + (System.getenv("GITHUB_RUN_NUMBER") ?: "0")
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
}

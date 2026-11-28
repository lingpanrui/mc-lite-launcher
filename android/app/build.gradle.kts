plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.mclite.android"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.mclite.android"
        minSdk = 24
        targetSdk = 34
        versionCode = 3
        versionName = "1.2.0"
    }

    // 固定 release 签名：CI 里由 secrets 解码 keystore 并注入这几个环境变量，
    // 本地构建时也可以手动设置同样的环境变量，保证跨版本签名一致、可覆盖升级。
    val ksEnv = System.getenv("MCLITE_KEYSTORE") ?: ""
    val ksFile: java.io.File? = when {
        ksEnv.isEmpty() -> null
        file(ksEnv).exists() -> file(ksEnv)
        rootProject.file(ksEnv).exists() -> rootProject.file(ksEnv)
        else -> null
    }
    signingConfigs {
        if (ksFile != null) {
            create("release") {
                storeFile = ksFile
                storePassword = System.getenv("MCLITE_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("MCLITE_KEY_ALIAS")
                keyPassword = System.getenv("MCLITE_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = signingConfigs.findByName("release")
        }
        debug {
            // 有固定 keystore 时，debug 包也用同一把 key，避免出现"签名不一致"的包
            signingConfig = signingConfigs.findByName("release")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        compose = true
    }

    composeOptions {
        kotlinCompilerExtensionVersion = "1.5.14"
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2024.06.00")
    implementation(composeBom)

    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.activity:activity-compose:1.9.1")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.4")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")

    debugImplementation("androidx.compose.ui:ui-tooling")
}

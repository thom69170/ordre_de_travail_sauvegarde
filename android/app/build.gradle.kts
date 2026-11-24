plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
}

android {
    namespace = "fr.notivo.otenvoi"
    compileSdk {
        version = release(37)
    }

    defaultConfig {
        applicationId = "fr.notivo.otenvoi"
        minSdk = 26 // Android 8+ : java.time disponible sans bibliothèque supplémentaire
        targetSdk = 37
        versionCode = 1
        versionName = "1.0"
    }

    buildTypes {
        release {
            optimization {
                enable = false
            }
            // Application personnelle : signée avec la clé de développement, installable directement.
            signingConfig = signingConfigs.getByName("debug")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
    buildFeatures {
        compose = true
    }
    packaging {
        // android-mail et android-activation embarquent chacun ces fichiers
        resources {
            excludes += setOf(
                "META-INF/LICENSE*", "META-INF/NOTICE*", "META-INF/DEPENDENCIES",
                "META-INF/*.md", "META-INF/INDEX.LIST", "META-INF/mailcap", "META-INF/mimetypes.default",
            )
        }
    }
    testOptions {
        unitTests.isReturnDefaultValues = true
    }
}

dependencies {
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.kotlinx.coroutines.android)

    // Appareil photo : capture EN MÉMOIRE (aucun fichier, aucune galerie)
    implementation(libs.androidx.camera.core)
    implementation(libs.androidx.camera.camera2)
    implementation(libs.androidx.camera.lifecycle)
    implementation(libs.androidx.camera.view)

    // Envoi (SMTP) et lecture de l'état (IMAP) de la boîte mail
    implementation(libs.android.mail)
    implementation(libs.android.activation)

    testImplementation(libs.junit)
    // Faux serveurs SMTP + IMAP pour tester l'envoi sans vraie boîte
    testImplementation(libs.greenmail) {
        exclude(group = "com.sun.mail", module = "javax.mail")
    }
    testImplementation(libs.org.json)
}

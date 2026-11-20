package com.junze.penpal.data.api

import com.google.gson.FieldNamingPolicy
import com.google.gson.GsonBuilder
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory

/**
 * Builds Retrofit for the built-in server address.
 *
 * The server address is fixed in the app — the user cannot change it
 * and there is no settings field for it anywhere.
 * All calls go to <baseUrl>/api/v1/… ; the auth token is passed per call
 * (see PenpalRepository).
 *
 * NOTE: as of 2026-11-20 the address does not respond yet (port 32123
 * closed). Calls fail with a connection error and the UI shows
 * "服务器未连接，请稍后再试" — the app must never claim it works.
 */
class ApiClient {

    /** Fixed built-in server address (HTTPS only). */
    val baseUrl: String = DEFAULT_BASE_URL

    private val service: ApiService = buildService(baseUrl)

    fun service(): ApiService = service

    private fun buildService(baseUrl: String): ApiService {
        val gson = GsonBuilder()
            .setFieldNamingPolicy(FieldNamingPolicy.LOWER_CASE_WITH_UNDERSCORES)
            .create()
        val logging = HttpLoggingInterceptor().apply {
            level = HttpLoggingInterceptor.Level.BASIC
        }
        val client = OkHttpClient.Builder()
            .addInterceptor(logging)
            .build()
        return Retrofit.Builder()
            .baseUrl("$baseUrl/api/v1/")
            .client(client)
            .addConverterFactory(GsonConverterFactory.create(gson))
            .build()
            .create(ApiService::class.java)
    }

    companion object {
        /** Built-in backend address. The app never lets the user change it. */
        const val DEFAULT_BASE_URL = "https://penpal.250886.xyz:32123"
    }
}
